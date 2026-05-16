from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from ..models import Channel, JobPost
from .base import Scraper


class RemoteOKScraper(Scraper):
    key = "remoteok"
    url = "https://remoteok.com/api"

    async def fetch(self, client: httpx.AsyncClient) -> AsyncIterator[JobPost]:
        r = await client.get(self.url, headers=self._client_headers(), timeout=30.0)
        r.raise_for_status()
        payload = r.json()
        # First element is a "legal" notice object — skip it.
        for item in payload[1:]:
            try:
                yield self._parse(item)
            except (KeyError, ValueError):
                continue

    def _parse(self, item: dict) -> JobPost:
        tags = [t.lower() for t in item.get("tags", []) if isinstance(t, str)]
        channel = (
            Channel.FREELANCE
            if any(t in tags for t in ("freelance", "contract"))
            else Channel.FT
        )
        posted = item.get("date") or item.get("epoch")
        posted_at = None
        if isinstance(posted, str):
            try:
                posted_at = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None
        return JobPost(
            source=self.key,
            external_id=str(item["id"]),
            url=item.get("url") or f"https://remoteok.com/remote-jobs/{item['id']}",
            title=item["position"],
            company=item.get("company"),
            location=item.get("location") or "Remote",
            description=item.get("description", ""),
            tags=tags,
            channel=channel,
            compensation=_format_salary(item),
            posted_at=posted_at,
        )


def _format_salary(item: dict) -> str | None:
    lo, hi = item.get("salary_min"), item.get("salary_max")
    if lo and hi:
        return f"${lo:,}–${hi:,}"
    if lo:
        return f"from ${lo:,}"
    return None
