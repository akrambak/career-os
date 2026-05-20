from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from ..models import JobPost
from ..watermark import WatermarkCtx


class Scraper(ABC):
    key: str
    user_agent: str = (
        "career-os/0.1 (+https://github.com/akrambak/career-os; me@bak-dev.com)"
    )

    @abstractmethod
    async def fetch(
        self,
        client: httpx.AsyncClient,
        watermarks: WatermarkCtx | None = None,
    ) -> AsyncIterator[JobPost]:
        """Yield JobPosts from this source.

        `watermarks` is optional — pre-existing scrapers can ignore it and
        will continue to do a full re-pull every run. Scrapers that opt-in
        read prior state via `watermarks.get(<source_key>)` and stage new
        state via `watermarks.record(<source_key>, ...)`. The crawler
        flushes records after fetch completes.
        """
        ...

    def _client_headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent, "Accept": "application/json, text/html"}

    def is_closed(self, response: httpx.Response) -> bool:
        """Optional source-specific signal that a posting is closed.

        Some sources serve a 200 page that says "this position is no longer
        accepting applications" — Wellfound does, RemoteOK does. Scrapers
        can override this to pattern-match the body and return True.

        Default: False (relies on the generic HTTP-status + redirect signals).
        See `career_os.recheck` for the calling convention.
        """
        return False
