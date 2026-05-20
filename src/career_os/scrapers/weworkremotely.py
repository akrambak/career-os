from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from ..models import Channel, JobPost
from ..watermark import WatermarkCtx
from .base import Scraper


class WeWorkRemotelyScraper(Scraper):
    key = "weworkremotely"
    feeds = [
        (
            "https://weworkremotely.com/categories/remote-programming-jobs.rss",
            Channel.FT,
            "programming",
        ),
        (
            "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
            Channel.FT,
            "fullstack",
        ),
    ]

    async def fetch(
        self,
        client: httpx.AsyncClient,
        watermarks: WatermarkCtx | None = None,
    ) -> AsyncIterator[JobPost]:
        seen: set[str] = set()
        for feed_url, channel, subfeed in self.feeds:
            wm_key = f"{self.key}:{subfeed}"
            prior = watermarks.get(wm_key) if watermarks else None

            # Conditional-GET headers: send If-Modified-Since + If-None-Match
            # when we have prior state. Server returns 304 → record
            # 'unchanged' + yield nothing for this sub-feed.
            req_headers = dict(self._client_headers())
            if prior:
                if prior.etag:
                    req_headers["If-None-Match"] = prior.etag
                if prior.last_modified:
                    req_headers["If-Modified-Since"] = prior.last_modified

            try:
                r = await client.get(feed_url, headers=req_headers, timeout=30.0)
            except httpx.HTTPError:
                if watermarks:
                    watermarks.record(wm_key, status="failed")
                continue

            if r.status_code == 304:
                if watermarks:
                    watermarks.record(wm_key, status="unchanged")
                continue
            try:
                r.raise_for_status()
            except httpx.HTTPError:
                if watermarks:
                    watermarks.record(wm_key, status="failed")
                continue

            if watermarks:
                watermarks.record(
                    wm_key, status="ok",
                    etag=r.headers.get("ETag"),
                    last_modified=r.headers.get("Last-Modified"),
                )

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
