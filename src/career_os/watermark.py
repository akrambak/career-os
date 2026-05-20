"""Per-source incremental-fetch watermarks (Tier 2, Upgrade 6).

A watermark is everything the next `fetch` needs to ask "what's new since
last time" instead of re-pulling the whole source. Four kinds:

  - RSS sources: `etag` + `last_modified` for If-None-Match / If-Modified-Since
  - JSON sources with stable IDs: `last_external_id` (break when we hit it)
  - Algolia / cursor sources: `last_cursor` (filter server-side)
  - Future browser sources: combination of the above as needed

Scrapers opt in. A scraper that takes no watermark arg behaves like before
(full re-pull); the crawler then records only a heartbeat row so the
dashboard's source-health view stays truthful.

Key conventions:
  - The TOP-LEVEL key for a scraper is `scraper.key` (e.g. 'remoteok').
  - A scraper with sub-feeds composes `<key>:<subfeed>` (e.g.
    'weworkremotely:programming'). The crawler records the top-level row
    automatically; sub-feed rows are recorded by the scraper.

Status values are a tiny vocabulary:
  - 'ok'         — fetch succeeded; jobs may or may not have been yielded
  - 'unchanged'  — source confirmed nothing new (304 / cursor returned empty)
  - 'failed'     — fetch raised; no jobs were ingested this run
  - 'partial'    — some jobs ingested but the run was cut short
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class Watermark:
    source: str
    last_fetched_at: datetime
    last_status: str
    etag: str | None = None
    last_modified: str | None = None
    last_external_id: str | None = None
    last_cursor: str | None = None
    notes: str | None = None


class WatermarkCtx:
    """Threaded through `Scraper.fetch` so scrapers can read prior
    watermarks and stage new ones. The crawler flushes staged writes after
    fetch completes — atomic from the source's perspective.
    """

    def __init__(self, getter: Callable[[str], Watermark | None]):
        self._get = getter
        # Staged writes keyed by source identifier (top-level or composite).
        self.records: dict[str, dict[str, Any]] = {}

    def get(self, source: str) -> Watermark | None:
        return self._get(source)

    def record(
        self, source: str, *,
        status: str | None = None,
        etag: str | None = None,
        last_modified: str | None = None,
        last_external_id: str | None = None,
        last_cursor: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Stage a write. Multiple calls for the same source merge."""
        bucket = self.records.setdefault(source, {})
        if status is not None:
            bucket["last_status"] = status
        if etag is not None:
            bucket["etag"] = etag
        if last_modified is not None:
            bucket["last_modified"] = last_modified
        if last_external_id is not None:
            bucket["last_external_id"] = last_external_id
        if last_cursor is not None:
            bucket["last_cursor"] = last_cursor
        if notes is not None:
            bucket["notes"] = notes

    def flush(self, save: Callable[..., None]) -> None:
        """Persist every staged record. `save(source=..., **fields)` is
        the Store-side write helper."""
        now = datetime.now(UTC).isoformat()
        for source, fields in self.records.items():
            # `last_status` is the only required field for save_watermark.
            # Default to 'ok' if the scraper forgot — better than crashing.
            fields.setdefault("last_status", "ok")
            save(source=source, last_fetched_at=now, **fields)
