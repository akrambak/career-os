"""Mention Hunter scrapers — HN, dev.to, GitHub code search.

Each scraper queries a public source for every term in DEFAULT_TERMS
(or the caller-supplied list) and upserts hits into the mentions table.
Per-source failures swallowed so one bad endpoint never kills the run.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

import httpx

from ..db import Store
from . import DEFAULT_TERMS, has_link, upsert_mention

logger = logging.getLogger(__name__)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
DEVTO_SEARCH_URL = "https://dev.to/api/articles"
GITHUB_CODE_SEARCH_URL = "https://api.github.com/search/code"

USER_AGENT = (
    "career-os/0.1 (+https://github.com/akrambak/career-os; me@bak-dev.com)"
)


async def scan_sources(
    store: Store, *,
    sources: list[str] | None = None,
    terms: Iterable[str] | None = None,
) -> dict[str, int]:
    """Run every (or selected) scraper. Returns {source: rows_upserted}.
    Per-source failures swallowed."""
    selected = set(sources) if sources else None
    term_list = list(terms) if terms else list(DEFAULT_TERMS)
    out: dict[str, int] = {}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for key, fn in SCAN_FUNCTIONS:
            if selected and key not in selected:
                continue
            try:
                out[key] = await fn(client, store, term_list)
            except Exception as exc:  # noqa: BLE001
                logger.warning("mention scan %s failed: %s", key, exc)
                out[key] = 0
    return out


# ---- HN search by query --------------------------------------------------

async def scan_hn(
    client: httpx.AsyncClient, store: Store, terms: list[str],
) -> int:
    n = 0
    for term in terms:
        try:
            r = await client.get(
                HN_SEARCH_URL,
                params={
                    "query": term, "tags": "(comment,story)",
                    "hitsPerPage": 25,
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=30.0,
            )
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        for hit in r.json().get("hits", []) or []:
            try:
                if _upsert_hn_hit(store, hit, term):
                    n += 1
            except (KeyError, ValueError):
                continue
    return n


def _upsert_hn_hit(store: Store, hit: dict, term: str) -> bool:
    object_id = str(hit.get("objectID") or "").strip()
    if not object_id:
        return False
    # Comment vs story URL.
    if "comment_text" in hit and hit.get("comment_text"):
        source_url = f"https://news.ycombinator.com/item?id={object_id}"
        body = hit.get("comment_text") or ""
    elif "story_text" in hit and hit.get("story_text"):
        source_url = f"https://news.ycombinator.com/item?id={object_id}"
        body = hit.get("story_text") or ""
    else:
        # Story with no body — fall back to title + URL fields.
        source_url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
        body = (hit.get("title") or "") + " " + (hit.get("url") or "")
    snippet = _snippet_around(body, term, max_len=280)
    if snippet is None:
        # Term wasn't in the body — Algolia matched on a sibling field.
        return False
    upsert_mention(
        store, source="hn", source_url=source_url,
        matched_term=term, context_snippet=snippet,
        has_link_value=has_link(body),
    )
    return True


# ---- dev.to article search ----------------------------------------------

async def scan_devto(
    client: httpx.AsyncClient, store: Store, terms: list[str],
) -> int:
    n = 0
    for term in terms:
        try:
            r = await client.get(
                DEVTO_SEARCH_URL,
                params={"per_page": 30, "tag": "", "top": 30},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=30.0,
            )
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        # dev.to's public /articles endpoint doesn't support full-text
        # search server-side; we filter client-side. Cheap because each
        # response is capped at 30 items.
        for article in r.json() or []:
            try:
                if _upsert_devto_article(store, article, term):
                    n += 1
            except (KeyError, ValueError):
                continue
    return n


def _upsert_devto_article(store: Store, article: dict, term: str) -> bool:
    title = (article.get("title") or "")
    description = (article.get("description") or "")
    body = title + " " + description
    if term.lower() not in body.lower():
        return False
    url = (article.get("url") or "").strip()
    if not url:
        return False
    snippet = _snippet_around(body, term, max_len=280)
    upsert_mention(
        store, source="devto", source_url=url,
        matched_term=term, context_snippet=snippet or body[:280],
        has_link_value=has_link(body),
    )
    return True


# ---- GitHub code search --------------------------------------------------

async def scan_github(
    client: httpx.AsyncClient, store: Store, terms: list[str],
) -> int:
    """Requires GITHUB_TOKEN env var. Without it, returns 0."""
    from ..config import Settings
    settings = Settings.load()
    token = getattr(settings, "github_token", None)
    if not token:
        return 0
    n = 0
    for term in terms:
        try:
            r = await client.get(
                GITHUB_CODE_SEARCH_URL,
                params={"q": term, "per_page": 30},
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        for item in r.json().get("items", []) or []:
            try:
                if _upsert_github_item(store, item, term):
                    n += 1
            except (KeyError, ValueError):
                continue
    return n


def _upsert_github_item(store: Store, item: dict, term: str) -> bool:
    html_url = (item.get("html_url") or "").strip()
    name = item.get("name") or ""
    repo = (item.get("repository") or {}).get("full_name") or ""
    if not html_url:
        return False
    snippet = f"file {name} in {repo}"
    # We don't fetch the file body — assume the match implies a real
    # reference in the source code; has_link is True because the file
    # listing itself is on github.com with an inherent URL context.
    upsert_mention(
        store, source="github", source_url=html_url,
        matched_term=term, context_snippet=snippet,
        has_link_value=True,
    )
    return True


# ---- helpers -------------------------------------------------------------

def _snippet_around(body: str, term: str, max_len: int = 280) -> str | None:
    """Return ~max_len chars centered on the first match of `term`. None
    if term isn't in body."""
    if not body or not term:
        return None
    idx = body.lower().find(term.lower())
    if idx < 0:
        return None
    half = max_len // 2
    start = max(0, idx - half)
    end = min(len(body), idx + half)
    snippet = body[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(body):
        snippet = snippet + "…"
    # Collapse whitespace for display.
    return " ".join(snippet.split())


SCAN_FUNCTIONS: tuple[tuple[str, ...], ...] = (
    ("hn", scan_hn),
    ("devto", scan_devto),
    ("github", scan_github),
)


__all__ = [
    "HN_SEARCH_URL", "DEVTO_SEARCH_URL", "GITHUB_CODE_SEARCH_URL",
    "SCAN_FUNCTIONS",
    "scan_sources", "scan_hn", "scan_devto", "scan_github",
]
