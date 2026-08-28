from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from ..models import Channel, JobPost
from ..salary import parse_from_numeric
from ..watermark import WatermarkCtx
from .base import Scraper

# Jobicy reports pay period as an adjective; our salary model keys on the noun.
# Anything unmapped (missing, or "weekly" — no bucket in salary) falls through to
# an empty period, so the structured comp abstains rather than being mislabeled.
_PERIOD_MAP = {"yearly": "year", "monthly": "month", "hourly": "hour", "daily": "day"}


class JobicyScraper(Scraper):
    """Jobicy — remote-jobs JSON API (v2). Global, EU-inclusive geo tags."""

    key = "jobicy"
    url = "https://jobicy.com/api/v2/remote-jobs"
    count = 50

    async def fetch(
        self,
        client: httpx.AsyncClient,
        watermarks: WatermarkCtx | None = None,
    ) -> AsyncIterator[JobPost]:
        try:
            r = await client.get(
                self.url,
                params={"count": self.count},
                headers=self._client_headers(),
                timeout=30.0,
            )
            r.raise_for_status()
        except httpx.HTTPError:
            if watermarks:
                watermarks.record(self.key, status="failed")
            return

        max_id_this_run: int | None = None
        yielded_any = False
        for item in r.json().get("jobs", []):
            job = self._parse(item)
            if job is None:
                continue
            item_id = _safe_int(item.get("id"))
            if item_id is not None and (max_id_this_run is None or item_id > max_id_this_run):
                max_id_this_run = item_id
            yielded_any = True
            yield job

        if watermarks:
            watermarks.record(
                self.key,
                status="ok" if yielded_any else "unchanged",
                last_external_id=str(max_id_this_run) if max_id_this_run is not None else None,
            )

    def _parse(self, item: dict) -> JobPost | None:
        external_id = str(item.get("id") or "").strip()
        url = (item.get("url") or "").strip()
        title = (item.get("jobTitle") or "").strip()
        if not external_id or not url or not title:
            return None

        job_types = [str(t).lower() for t in item.get("jobType") or []]
        channel = Channel.FREELANCE if any(
            "contract" in t or "freelance" in t for t in job_types
        ) else Channel.FT

        raw_html = item.get("jobDescription") or item.get("jobExcerpt") or ""
        description = re.sub(r"<[^>]+>", " ", raw_html)
        description = re.sub(r"\s+", " ", description).strip()

        parsed = parse_from_numeric(
            item.get("salaryMin"), item.get("salaryMax"),
            currency=str(item.get("salaryCurrency") or "USD").upper(),
            period=_PERIOD_MAP.get(str(item.get("salaryPeriod") or "").lower(), ""),
            raw=_format_salary(item),
        )
        return JobPost(
            source=self.key,
            external_id=external_id,
            url=url,
            title=title,
            company=item.get("companyName") or None,
            location=item.get("jobGeo") or "Remote",
            description=description,
            tags=[str(t).lower() for t in item.get("jobIndustry") or []],
            channel=channel,
            compensation=_format_salary(item),
            parsed_compensation=parsed if parsed.known else None,
            posted_at=_parse_iso(item.get("pubDate")),
        )


def _format_salary(item: dict) -> str | None:
    lo, hi = item.get("salaryMin"), item.get("salaryMax")
    cur = str(item.get("salaryCurrency") or "USD").upper()
    if lo and hi:
        return f"{cur} {int(lo):,}–{int(hi):,}"
    if lo:
        return f"{cur} from {int(lo):,}"
    return None


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
