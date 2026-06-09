from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from ..db import Store
from ..scrapers import REGISTRY, Scraper
from ..watermark import WatermarkCtx

logger = logging.getLogger(__name__)


async def crawl(
    store: Store, scraper_keys: list[str] | None = None,
    *, use_watermarks: bool = True,
) -> dict[str, int]:
    """Run scrapers concurrently, upsert results, return per-source new-job
    counts.

    `use_watermarks=False` is the `--full-refresh` escape hatch — every
    scraper receives None instead of a WatermarkCtx, so opted-in scrapers
    fall back to full re-pull. Watermark rows are still written (so the
    next normal run has fresh state).
    """
    keys = scraper_keys or list(REGISTRY)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        async def run_guarded(key: str) -> tuple[str, int]:
            try:
                return key, await _run_one(
                    REGISTRY[key](), client, store, use_watermarks
                )
            except Exception as exc:  # noqa: BLE001 — bad source shouldn't kill the crawl
                logger.warning("scraper %s failed: %s", key, exc)
                # Record the failure so dashboard source-health sees it.
                store.save_watermark(
                    source=key,
                    last_fetched_at=datetime.now(UTC).isoformat(),
                    last_status="failed",
                    notes=f"{type(exc).__name__}: {exc}"[:200],
                )
                return key, 0

        pairs = await asyncio.gather(*(run_guarded(key) for key in keys))
    return dict(pairs)


async def _run_one(
    scraper: Scraper, client: httpx.AsyncClient, store: Store,
    use_watermarks: bool,
) -> int:
    ctx = WatermarkCtx(getter=store.get_watermark) if use_watermarks else None
    jobs = [job async for job in scraper.fetch(client, ctx)]
    new = store.upsert_jobs(jobs)

    # Flush opt-in scraper writes. Always also record a top-level
    # heartbeat for the scraper key so source-health stays truthful even
    # for scrapers that don't opt-in to per-sub-feed records.
    now = datetime.now(UTC).isoformat()
    if ctx is not None:
        ctx.flush(store.save_watermark)
    top_level_status = _derive_top_level_status(ctx, scraper.key, new)
    store.save_watermark(
        source=scraper.key,
        last_fetched_at=now,
        last_status=top_level_status,
    )
    return new


def _derive_top_level_status(
    ctx: WatermarkCtx | None, scraper_key: str, new_count: int,
) -> str:
    """Top-level row status for a scraper.

    - If the scraper recorded its OWN top-level row in ctx, respect it.
    - Else if any sub-feed in ctx is 'failed', mark 'partial' (some went,
      some didn't).
    - Else if every sub-feed is 'unchanged' AND new_count == 0, 'unchanged'.
    - Else 'ok'.
    """
    if ctx is None:
        return "ok"
    own = ctx.records.get(scraper_key, {}).get("last_status")
    if own:
        return own
    sub_statuses = [
        bucket.get("last_status") for src, bucket in ctx.records.items()
        if src != scraper_key
    ]
    if any(s == "failed" for s in sub_statuses):
        return "partial" if new_count > 0 else "failed"
    if sub_statuses and all(s == "unchanged" for s in sub_statuses) and new_count == 0:
        return "unchanged"
    return "ok"


def crawl_sync(
    store: Store, scraper_keys: list[str] | None = None,
    *, use_watermarks: bool = True,
) -> dict[str, int]:
    return asyncio.run(crawl(store, scraper_keys, use_watermarks=use_watermarks))
