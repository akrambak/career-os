from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from ..models import Channel, JobPost
from ..salary import parse as parse_salary
from ..watermark import WatermarkCtx
from .base import Scraper


class RemotiveScraper(Scraper):
    """Remotive — remote-jobs JSON API. Includes both FT and freelance contracts."""

    key = "remotive"
    url = "https://remotive.com/api/remote-jobs"
    categories = ("software-dev",)

    async def fetch(
        self,
        client: httpx.AsyncClient,
        watermarks: WatermarkCtx | None = None,
    ) -> AsyncIterator[JobPost]:
        max_id_this_run: int | None = None
        any_yielded = False
        any_failed = False

        for category in self.categories:
            wm_key = f"{self.key}:{category}"
            prior = watermarks.get(wm_key) if watermarks else None
            prior_id_int = _safe_int(prior.last_external_id) if prior else None

            try:
                r = await client.get(
                    self.url,
                    params={"category": category},
                    headers=self._client_headers(),
                    timeout=30.0,
                )
                r.raise_for_status()
            except httpx.HTTPError:
                any_failed = True
                if watermarks:
                    watermarks.record(wm_key, status="failed")
                continue

            jobs = r.json().get("jobs", [])
            # Remotive returns id-descending. Stop at the prior high-water mark.
            sub_max: int | None = None
            sub_yielded = False
            for item in jobs:
                item_id = _safe_int(item.get("id"))
                if item_id is not None and prior_id_int is not None and item_id <= prior_id_int:
                    break
                if item_id is not None and (sub_max is None or item_id > sub_max):
                    sub_max = item_id
                job = self._parse(item)
                if job:
                    sub_yielded = True
                    any_yielded = True
                    yield job
            if watermarks:
                new_id = sub_max if sub_max is not None else prior_id_int
                watermarks.record(
                    wm_key,
                    status="ok" if sub_yielded else "unchanged",
                    last_external_id=str(new_id) if new_id is not None else None,
                )
            if sub_max is not None and (max_id_this_run is None or sub_max > max_id_this_run):
                max_id_this_run = sub_max

        # Top-level row for the scraper key.
        if watermarks:
            if any_failed and not any_yielded:
                watermarks.record(self.key, status="failed")
            elif any_failed:
                watermarks.record(self.key, status="partial")
            elif not any_yielded:
                watermarks.record(self.key, status="unchanged")
            else:
                watermarks.record(self.key, status="ok")
            if max_id_this_run is not None:
                watermarks.record(self.key, last_external_id=str(max_id_this_run))

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
        raw_salary = (item.get("salary") or "").strip() or None
        # Remotive's salary field is free-text — regex pass via salary.parse.
        # On hourly/contract jobs, the period heuristic + ISO-code detection
        # in salary.py do the heavy lifting.
        parsed = parse_salary(raw_salary) if raw_salary else None
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
            compensation=raw_salary,
            parsed_compensation=parsed if parsed and parsed.known else None,
            posted_at=posted_at,
        )


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
