from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from ..models import Channel, JobPost
from ..salary import parse_from_numeric
from ..watermark import WatermarkCtx
from .base import Scraper


class RemoteOKScraper(Scraper):
    key = "remoteok"
    url = "https://remoteok.com/api"

    async def fetch(
        self,
        client: httpx.AsyncClient,
        watermarks: WatermarkCtx | None = None,
    ) -> AsyncIterator[JobPost]:
        prior = watermarks.get(self.key) if watermarks else None
        last_seen_id = prior.last_external_id if prior else None

        r = await client.get(self.url, headers=self._client_headers(), timeout=30.0)
        r.raise_for_status()
        payload = r.json()

        # RemoteOK's payload is roughly date-descending — newest first. We
        # iterate from the top, stop the moment we hit `last_seen_id`, and
        # record the FIRST id of this run as the new high-water mark.
        # First element is a "legal" notice object — skip it.
        items = payload[1:]
        max_id_this_run: str | None = None
        yielded_any = False
        for item in items:
            item_id = str(item.get("id", "")) if item.get("id") is not None else ""
            if not item_id:
                continue
            if last_seen_id and item_id == last_seen_id:
                # We've caught up to the previous high-water mark — stop.
                break
            if max_id_this_run is None:
                max_id_this_run = item_id
            try:
                yield self._parse(item)
                yielded_any = True
            except (KeyError, ValueError):
                continue

        if watermarks:
            status = "ok" if yielded_any else ("unchanged" if last_seen_id else "ok")
            watermarks.record(
                self.key, status=status,
                last_external_id=max_id_this_run or last_seen_id,
            )

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
        # RemoteOK gives us numeric salary fields directly — skip the regex
        # pass and build the Compensation from the structured values.
        raw_salary = _format_salary(item)
        parsed = parse_from_numeric(
            item.get("salary_min"), item.get("salary_max"),
            currency="USD", period="year",
            raw=raw_salary or "",
        )
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
            compensation=raw_salary,
            parsed_compensation=parsed if parsed.known else None,
            posted_at=posted_at,
        )


def _format_salary(item: dict) -> str | None:
    lo, hi = item.get("salary_min"), item.get("salary_max")
    if lo and hi:
        return f"${lo:,}–${hi:,}"
    if lo:
        return f"from ${lo:,}"
    return None
