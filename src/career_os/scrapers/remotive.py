from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from ..models import Channel, JobPost
from .base import Scraper


class RemotiveScraper(Scraper):
    """Remotive — remote-jobs JSON API. Includes both FT and freelance contracts."""

    key = "remotive"
    url = "https://remotive.com/api/remote-jobs"
    categories = ("software-dev",)

    async def fetch(self, client: httpx.AsyncClient) -> AsyncIterator[JobPost]:
        for category in self.categories:
            try:
                r = await client.get(
                    self.url,
                    params={"category": category},
                    headers=self._client_headers(),
                    timeout=30.0,
                )
                r.raise_for_status()
            except httpx.HTTPError:
                continue
            for item in r.json().get("jobs", []):
                job = self._parse(item)
                if job:
                    yield job

    def _parse(self, item: dict) -> JobPost | None:
        external_id = str(item.get("id") or "")
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not external_id or not url or not title:
            return None
        job_type = (item.get("job_type") or "").lower()
        channel = Channel.FREELANCE if any(
            t in job_type for t in ("contract", "freelance")
        ) else Channel.FT
        description = re.sub(r"<[^>]+>", " ", item.get("description") or "")
        description = re.sub(r"\s+", " ", description).strip()
        posted = item.get("publication_date")
        posted_at: datetime | None = None
        if posted:
            try:
                posted_at = datetime.fromisoformat(posted.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None
        return JobPost(
            source=self.key,
            external_id=external_id,
            url=url,
            title=title,
            company=item.get("company_name") or None,
            location=item.get("candidate_required_location") or "Remote",
            description=description,
            tags=[t.lower() for t in (item.get("tags") or []) if isinstance(t, str)],
            channel=channel,
            compensation=(item.get("salary") or "").strip() or None,
            posted_at=posted_at,
        )
