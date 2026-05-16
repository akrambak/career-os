from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from ..models import JobPost


class Scraper(ABC):
    key: str
    user_agent: str = (
        "career-os/0.1 (+https://github.com/akrambak/career-os; me@bak-dev.com)"
    )

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> AsyncIterator[JobPost]:
        ...

    def _client_headers(self) -> dict[str, str]:
        return {"User-Agent": self.user_agent, "Accept": "application/json, text/html"}
