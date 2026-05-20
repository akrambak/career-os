"""Trend scrapers — HN frontpage, dev.to top-of-week, Tavily web search.

Each scraper is async and upserts into the `trends` table via the
`trends` module. Failures swallowed per-source so one bad endpoint never
kills the scan.

To add a new source: write `async def scan_<key>(client, store, profile)`
and add it to `SCAN_FUNCTIONS`.
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx

from ..db import Store
from ..models import Profile
from . import upsert_trend

logger = logging.getLogger(__name__)

HN_FRONTPAGE_URL = "https://hn.algolia.com/api/v1/search"
DEVTO_TOP_URL = "https://dev.to/api/articles"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

USER_AGENT = (
    "career-os/0.1 (+https://github.com/akrambak/career-os; me@bak-dev.com)"
)


# ---- scan orchestrator ---------------------------------------------------

ScanFn = Callable[[httpx.AsyncClient, Store, Profile | None], Awaitable[int]]


async def scan_sources(
    store: Store,
    profile: Profile | None = None,
    *, sources: list[str] | None = None,
) -> dict[str, int]:
    """Run every (or selected) scraper concurrently. Returns
    `{source_key: rows_upserted}`. Per-scraper failures are logged and
    recorded as 0 — they never raise out of this function."""
    selected = set(sources) if sources else None
    out: dict[str, int] = {}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for key, fn in SCAN_FUNCTIONS:
            if selected and key not in selected:
                continue
            try:
                out[key] = await fn(client, store, profile)
            except Exception as exc:  # noqa: BLE001 — never kill the scan
                logger.warning("trend scan %s failed: %s", key, exc)
                out[key] = 0
    return out


# ---- HN frontpage --------------------------------------------------------

async def scan_hn(
    client: httpx.AsyncClient, store: Store, profile: Profile | None,
) -> int:
    """Scrape HN frontpage stories via Algolia search."""
    r = await client.get(
        HN_FRONTPAGE_URL,
        params={"tags": "front_page", "hitsPerPage": 50},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30.0,
    )
    r.raise_for_status()
    payload = r.json()
    n = 0
    for hit in payload.get("hits", []):
        try:
            if _upsert_hn_hit(store, hit, profile):
                n += 1
        except (KeyError, ValueError):
            continue
    return n


def _upsert_hn_hit(store: Store, hit: dict, profile: Profile | None) -> bool:
    object_id = str(hit.get("objectID") or "").strip()
    title = (hit.get("title") or "").strip()
    url = (hit.get("url") or "").strip() or f"https://news.ycombinator.com/item?id={object_id}"
    if not object_id or not title:
        return False
    score = int(hit.get("points") or 0)
    comment_count = int(hit.get("num_comments") or 0)
    fetched_at = _parse_iso(hit.get("created_at")) or datetime.now(UTC)
    tags = [t for t in (hit.get("_tags") or []) if isinstance(t, str)]
    upsert_trend(
        store,
        source="hn", external_id=object_id, url=url, title=title,
        score=score, comment_count=comment_count, tags=tags,
        raw={k: hit.get(k) for k in ("author", "story_text", "_tags")},
        fetched_at=fetched_at,
        profile=profile,
    )
    return True


# ---- dev.to top-of-week --------------------------------------------------

async def scan_devto(
    client: httpx.AsyncClient, store: Store, profile: Profile | None,
) -> int:
    r = await client.get(
        DEVTO_TOP_URL,
        params={"top": 7, "per_page": 50},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=30.0,
    )
    r.raise_for_status()
    n = 0
    for article in r.json():
        try:
            if _upsert_devto_article(store, article, profile):
                n += 1
        except (KeyError, ValueError):
            continue
    return n


def _upsert_devto_article(
    store: Store, article: dict, profile: Profile | None,
) -> bool:
    article_id = str(article.get("id") or "").strip()
    title = (article.get("title") or "").strip()
    url = (article.get("url") or "").strip()
    if not article_id or not title or not url:
        return False
    score = int(article.get("positive_reactions_count") or 0)
    comment_count = int(article.get("comments_count") or 0)
    tags = [
        t.strip().lower() for t in (article.get("tag_list") or [])
        if isinstance(t, str)
    ]
    fetched_at = _parse_iso(article.get("published_at")) or datetime.now(UTC)
    summary = (article.get("description") or "").strip() or None
    upsert_trend(
        store,
        source="devto", external_id=article_id, url=url, title=title,
        summary=summary,
        score=score, comment_count=comment_count, tags=tags,
        raw={
            "cover_image": article.get("cover_image"),
            "reading_time_minutes": article.get("reading_time_minutes"),
            "user": (article.get("user") or {}).get("username"),
        },
        fetched_at=fetched_at,
        profile=profile,
    )
    return True


# ---- Tavily web search ---------------------------------------------------

async def scan_tavily(
    client: httpx.AsyncClient, store: Store, profile: Profile | None,
) -> int:
    """Web-search trend pulse via Tavily. Skipped if TAVILY_API_KEY unset."""
    from ..config import Settings
    settings = Settings.load()
    api_key = getattr(settings, "tavily_api_key", None)
    if not api_key:
        return 0
    queries = _derive_tavily_queries(profile)
    n = 0
    for query in queries:
        try:
            r = await client.post(
                TAVILY_SEARCH_URL,
                json={
                    "api_key": api_key, "query": query,
                    "search_depth": "basic", "max_results": 5,
                    "include_answer": False,
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=30.0,
            )
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError:
            continue
        for result in data.get("results", []) or []:
            try:
                if _upsert_tavily_result(store, result, profile):
                    n += 1
            except (KeyError, ValueError):
                continue
    return n


def _derive_tavily_queries(profile: Profile | None) -> list[str]:
    base = [
        "latest AI and LLM news this week",
        "trending developer tools 2026",
    ]
    if profile is None:
        return base
    # One query per non-trivial new_stack term to track the user's adopted stack.
    extras = []
    for term in profile.new_stack[:3]:
        extras.append(f"latest {term} news this week")
    return base + extras


def _upsert_tavily_result(
    store: Store, result: dict, profile: Profile | None,
) -> bool:
    url = (result.get("url") or "").strip()
    title = (result.get("title") or "").strip()
    if not url or not title:
        return False
    # Tavily doesn't give us a stable id — hash the URL.
    external_id = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    # Tavily's 0..1 relevance score → multiply by 100 so it shares a range
    # with HN points / devto reactions in our base-score formula.
    raw_score = float(result.get("score") or 0.0)
    score = int(raw_score * 100)
    summary = (result.get("content") or "").strip()[:600] or None
    upsert_trend(
        store,
        source="tavily", external_id=external_id, url=url, title=title,
        summary=summary,
        score=score, comment_count=0, tags=[],
        raw={"raw_score": raw_score, "snippet": result.get("content")},
        fetched_at=datetime.now(UTC),
        profile=profile,
    )
    return True


# ---- helpers -------------------------------------------------------------

def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


SCAN_FUNCTIONS: tuple[tuple[str, ScanFn], ...] = (
    ("hn", scan_hn),
    ("devto", scan_devto),
    ("tavily", scan_tavily),
)


__all__ = [
    "SCAN_FUNCTIONS", "scan_sources",
    "scan_hn", "scan_devto", "scan_tavily",
]
