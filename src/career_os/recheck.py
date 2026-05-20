"""Stale-job detection (Tier 3, Upgrade 8).

Re-checks job URLs and marks closed postings so `top` / `digest` / the
dashboard stop surfacing dead links.

Three closed signals, in order of preference:

  1. **HTTP 404 / 410** — definitive: the listing is gone.
  2. **HTTP 200 but redirected** to a generic listings index — the source
     swallows expired listings into its catalog. We pattern-match the final
     URL.
  3. **Source-specific marker** — some sources serve a 200 page that says
     "this position is no longer accepting applications" in the body. The
     scraper's `is_closed(response)` hook detects these.

Transient 5xx / network errors bump `recheck_attempts`. Three failed attempts
across separate runs flip the job to `is_closed=1` with reason `unreachable`
— cleaner than letting dead URLs linger forever.

Recheck runs as `career-os recheck`, NOT as part of `career-os fetch`. The
two have different cadences (weekly vs daily) and different failure modes.
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import httpx

from .db import Store
from .models import JobPost
from .scrapers import REGISTRY

logger = logging.getLogger(__name__)

# Final-URL path patterns that indicate the source redirected us to a generic
# listings or expired-job page. Conservative — we'd rather miss a closure
# than wrongly mark a live posting closed.
_LISTINGS_PATTERNS = (
    re.compile(r"/jobs/?$", re.IGNORECASE),
    re.compile(r"/remote-jobs/?$", re.IGNORECASE),
    re.compile(r"/closed\b", re.IGNORECASE),
    re.compile(r"/expired\b", re.IGNORECASE),
    re.compile(r"/no[-_]longer[-_]available\b", re.IGNORECASE),
)

# After this many consecutive transient failures, mark closed with reason
# 'unreachable'. Three is the canonical 3-strikes threshold.
TRANSIENT_STRIKE_LIMIT = 3


@dataclass(frozen=True)
class RecheckOutcome:
    job_key: str
    decision: str   # 'kept' | 'closed' | 'transient'
    reason: str | None
    status_code: int | None


async def recheck(
    store: Store, *, limit: int = 200, max_age_days: int = 7,
    source: str | None = None, concurrency: int = 10,
) -> list[RecheckOutcome]:
    """Recheck up to `limit` candidate jobs, return per-job outcomes."""
    candidates = store.recheck_candidates(
        limit=limit, max_age_days=max_age_days, source=source,
    )
    if not candidates:
        return []
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        outcomes = await asyncio.gather(
            *[_check_one(client, sem, store, job) for job in candidates],
            return_exceptions=False,
        )
    return outcomes


async def _check_one(
    client: httpx.AsyncClient, sem: asyncio.Semaphore,
    store: Store, job: JobPost,
) -> RecheckOutcome:
    async with sem:
        url = str(job.url)
        try:
            response = await client.get(
                url,
                headers={"User-Agent": _ua_for(job.source)},
                timeout=15.0,
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            attempts = store.mark_recheck_attempt(job.key, transient=True)
            if attempts >= TRANSIENT_STRIKE_LIMIT:
                store.mark_closed(job.key, reason="unreachable")
                return RecheckOutcome(job.key, "closed", "unreachable", None)
            return RecheckOutcome(
                job.key, "transient", f"{type(exc).__name__}: {exc}", None,
            )

    return _decide(store, job, response)


def _decide(store: Store, job: JobPost, response: httpx.Response) -> RecheckOutcome:
    status = response.status_code
    if status in (404, 410):
        store.mark_closed(job.key, reason="gone")
        return RecheckOutcome(job.key, "closed", "gone", status)

    if 500 <= status < 600:
        attempts = store.mark_recheck_attempt(job.key, transient=True)
        if attempts >= TRANSIENT_STRIKE_LIMIT:
            store.mark_closed(job.key, reason="unreachable")
            return RecheckOutcome(job.key, "closed", "unreachable", status)
        return RecheckOutcome(job.key, "transient", f"http {status}", status)

    if status >= 400:
        # 4xx other than 404/410: don't auto-close (could be auth/rate-limit).
        # Bump attempts so it eventually times out.
        attempts = store.mark_recheck_attempt(job.key, transient=True)
        if attempts >= TRANSIENT_STRIKE_LIMIT:
            store.mark_closed(job.key, reason="unreachable")
            return RecheckOutcome(job.key, "closed", "unreachable", status)
        return RecheckOutcome(job.key, "transient", f"http {status}", status)

    # 200-ish. Two further checks:
    final_url = str(response.url)
    if final_url != str(job.url):
        # Compare the final path against known listings/expired patterns.
        path = httpx.URL(final_url).path
        if any(pat.search(path) for pat in _LISTINGS_PATTERNS):
            store.mark_closed(job.key, reason="redirected-to-listings")
            return RecheckOutcome(
                job.key, "closed", "redirected-to-listings", status,
            )

    # Source-specific signal.
    scraper_cls = REGISTRY.get(job.source)
    if scraper_cls is not None:
        try:
            scraper = scraper_cls()
            if scraper.is_closed(response):
                store.mark_closed(job.key, reason="source-marker")
                return RecheckOutcome(job.key, "closed", "source-marker", status)
        except Exception as exc:  # noqa: BLE001 — bad scraper hook isn't fatal
            logger.warning("is_closed hook failed for %s: %s", job.key, exc)

    # Still alive.
    store.mark_recheck_attempt(job.key, transient=False)
    return RecheckOutcome(job.key, "kept", None, status)


def _ua_for(source: str) -> str:
    """Use the scraper's UA if we have one, else a generic Career-OS UA."""
    cls = REGISTRY.get(source)
    if cls is not None:
        return cls.user_agent
    return "career-os/0.1 (+https://github.com/akrambak/career-os; me@bak-dev.com)"


def summarize(outcomes: list[RecheckOutcome]) -> dict[str, int]:
    """Bucket outcomes by decision for CLI display."""
    out = {"kept": 0, "closed": 0, "transient": 0}
    for o in outcomes:
        out[o.decision] = out.get(o.decision, 0) + 1
    return out


__all__ = [
    "RecheckOutcome", "TRANSIENT_STRIKE_LIMIT",
    "recheck", "summarize",
]
