from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime
from html import unescape

import httpx

from ..models import Channel, JobPost
from ..salary import parse as parse_salary
from ..watermark import WatermarkCtx
from .base import Scraper
from .hn_freelancer import _extract_fields, _first_line, _safe_int

ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
ALGOLIA_ITEM = "https://hn.algolia.com/api/v1/items/{}"


class HNWhoIsHiringScraper(Scraper):
    """
    HN monthly 'Ask HN: Who is hiring?' thread — top-level comments are
    real hiring posts from real companies (mostly startups). Most are FT;
    a small fraction explicitly say REMOTE | CONTRACT.

    Higher noise floor than the freelance thread, but much larger volume —
    typically 600-900 top-level comments per month. The Claude scorer is
    what makes this source worthwhile vs grepping by hand.
    """

    key = "hn_whoishiring"

    async def fetch(
        self,
        client: httpx.AsyncClient,
        watermarks: WatermarkCtx | None = None,
    ) -> AsyncIterator[JobPost]:
        story_id = await self._find_latest_thread(client)
        if story_id is None:
            return

        # Watermark per story_id (thread roll-over resets state).
        wm_key = f"{self.key}:{story_id}"
        prior = watermarks.get(wm_key) if watermarks else None
        cursor = _safe_int(prior.last_cursor) if prior else None

        r = await client.get(
            ALGOLIA_ITEM.format(story_id),
            headers=self._client_headers(),
            timeout=60.0,
        )
        r.raise_for_status()
        thread = r.json()
        max_created_at = cursor or 0
        yielded_any = False
        for child in thread.get("children", []) or []:
            created_at_i = _safe_int(child.get("created_at_i"))
            if cursor is not None and created_at_i is not None and created_at_i <= cursor:
                continue
            job = self._parse(child)
            if job:
                yielded_any = True
                yield job
                if created_at_i is not None and created_at_i > max_created_at:
                    max_created_at = created_at_i

        if watermarks:
            status = "ok" if yielded_any else ("unchanged" if cursor else "ok")
            watermarks.record(
                wm_key, status=status,
                last_cursor=str(max_created_at) if max_created_at else None,
            )

    async def _find_latest_thread(self, client: httpx.AsyncClient) -> int | None:
        params = {
            "query": "Ask HN: Who is hiring?",
            "tags": "story,author_whoishiring",
            "hitsPerPage": 5,
        }
        r = await client.get(
            ALGOLIA_SEARCH, params=params,
            headers=self._client_headers(), timeout=30.0,
        )
        r.raise_for_status()
        for hit in r.json().get("hits", []):
            title = hit.get("title") or ""
            if title.startswith("Ask HN: Who is hiring?"):
                return int(hit["objectID"])
        return None

    def _parse(self, comment: dict) -> JobPost | None:
        text = comment.get("text") or ""
        if not text:
            return None
        plain = unescape(re.sub(r"<[^>]+>", " ", text))
        plain = re.sub(r"\s+", " ", plain).strip()
        if len(plain) < 60:
            return None
        cid = comment.get("id")
        if not cid:
            return None
        # Heuristic: most hiring posts open with COMPANY | TITLE | LOCATION
        # at the very start of the comment.
        upper = plain[:80].upper()
        looks_like_hiring = (
            "|" in plain[:120]
            or any(kw in upper for kw in ("HIRING", "REMOTE", "ONSITE", "HYBRID"))
            or re.match(r"^[A-Z][A-Za-z0-9\s&.]+\|", plain)
        )
        if not looks_like_hiring:
            return None
        created = comment.get("created_at")
        posted_at: datetime | None = None
        if created:
            try:
                posted_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None
        extracted = _extract_fields(plain)
        title = _hiring_title(plain) or _first_line(plain, max_len=120) or "HN hiring post"
        # If REMOTE | CONTRACT appears, mark freelance; otherwise FT
        is_contract = bool(re.search(r"\bCONTRACT(?:OR)?\b|\bFREELANCE\b", plain, re.IGNORECASE))
        channel = Channel.FREELANCE if is_contract else Channel.FT
        parsed_comp = (
            parse_salary(extracted["budget"]) if extracted["budget"] else None
        )
        return JobPost(
            source=self.key,
            external_id=str(cid),
            url=f"https://news.ycombinator.com/item?id={cid}",
            title=title,
            company=_company(plain),
            location=extracted["location"] or "Unspecified",
            description=plain,
            tags=["hn"] + extracted["stack"],
            channel=channel,
            compensation=extracted["budget"],
            parsed_compensation=parsed_comp if parsed_comp and parsed_comp.known else None,
            posted_at=posted_at,
        )


def _hiring_title(plain: str) -> str | None:
    # Pattern "COMPANY | TITLE | LOCATION | ..." — take the second pipe segment.
    parts = [p.strip() for p in plain.split("|")]
    if len(parts) >= 2 and 4 <= len(parts[1]) <= 120:
        return parts[1]
    return None


def _company(plain: str) -> str | None:
    parts = [p.strip() for p in plain.split("|")]
    if parts and 1 <= len(parts[0]) <= 60 and not parts[0].lower().startswith("seeking"):
        return parts[0]
    return None
