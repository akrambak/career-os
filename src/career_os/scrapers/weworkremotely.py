from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from ..models import Channel, JobPost
from .base import Scraper


class WeWorkRemotelyScraper(Scraper):
    key = "weworkremotely"
    feeds = [
        ("https://weworkremotely.com/categories/remote-programming-jobs.rss", Channel.FT),
        (
            "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
            Channel.FT,
        ),
    ]

    async def fetch(self, client: httpx.AsyncClient) -> AsyncIterator[JobPost]:
        seen: set[str] = set()
        for feed_url, channel in self.feeds:
            try:
                r = await client.get(feed_url, headers=self._client_headers(), timeout=30.0)
                r.raise_for_status()
            except httpx.HTTPError:
                continue
            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                job = self._parse(item, channel)
                if job and job.external_id not in seen:
                    seen.add(job.external_id)
                    yield job

    def _parse(self, item: ET.Element, channel: Channel) -> JobPost | None:
        link = (item.findtext("link") or "").strip()
        title = (item.findtext("title") or "").strip()
        if not link or not title:
            return None
        external_id = link.rstrip("/").split("/")[-1]
        company = None
        position = title
        if ":" in title:
            company, _, position = title.partition(":")
            company, position = company.strip(), position.strip()
        description = (item.findtext("description") or "").strip()
        # WeWorkRemotely descriptions are HTML — strip tags for the scorer prompt.
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip()
        pub = item.findtext("pubDate")
        posted_at: datetime | None = None
        if pub:
            try:
                posted_at = parsedate_to_datetime(pub)
            except (TypeError, ValueError):
                posted_at = None
        return JobPost(
            source=self.key,
            external_id=external_id,
            url=link,
            title=position,
            company=company,
            location="Remote",
            description=description,
            tags=[],
            channel=channel,
            posted_at=posted_at,
        )
