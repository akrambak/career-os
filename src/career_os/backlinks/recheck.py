"""Async batch recheck for backlinks. Companion to the pure decision
helpers in `__init__.py`."""
from __future__ import annotations

import asyncio
import logging

import httpx

from ..db import Store
from . import (
    TRANSIENT_STRIKE_LIMIT,
    RecheckOutcome,
    candidates_for_recheck,
    decide_from_response,
    detect_rel,
    update_rel,
    update_status,
)

logger = logging.getLogger(__name__)

USER_AGENT = (
    "career-os/0.1 (+https://github.com/akrambak/career-os; me@bak-dev.com)"
)


async def recheck_all(
    store: Store, *, limit: int = 200, max_age_days: int = 7,
    concurrency: int = 10,
) -> list[RecheckOutcome]:
    candidates = candidates_for_recheck(
        store, limit=limit, max_age_days=max_age_days,
    )
    if not candidates:
        return []
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(follow_redirects=True) as client:
        outcomes = await asyncio.gather(
            *[_check_one(client, sem, store, bl) for bl in candidates],
            return_exceptions=False,
        )
    return outcomes


async def _check_one(
    client: httpx.AsyncClient, sem: asyncio.Semaphore,
    store: Store, backlink,
) -> RecheckOutcome:
    async with sem:
        try:
            response = await client.get(
                backlink.source_url,
                headers={"User-Agent": USER_AGENT},
                timeout=15.0,
            )
        except (httpx.HTTPError, TimeoutError) as exc:
            return _record_transient(
                store, backlink, status_code=None,
                detail=f"{type(exc).__name__}: {exc}",
            )
    body = response.text if response.status_code < 400 else None
    final_url = str(response.url) if response.url else None
    decision, detail = decide_from_response(
        target_url=backlink.target_url,
        status_code=response.status_code,
        body=body, final_url=final_url,
    )
    if decision == "transient":
        return _record_transient(
            store, backlink, status_code=response.status_code, detail=detail,
        )
    # Successful classification → update status, reset attempts.
    update_status(store, backlink.id, decision)
    # Bonus: when the link is live, re-classify rel from the rendered HTML.
    if decision == "live" and body:
        new_rel = detect_rel(body, backlink.target_url)
        if new_rel and new_rel != backlink.rel:
            update_rel(store, backlink.id, new_rel)
            logger.info("backlink %d rel changed: %s -> %s",
                        backlink.id, backlink.rel, new_rel)
    return RecheckOutcome(
        backlink_id=backlink.id, decision=decision,
        status_code=response.status_code, detail=detail,
    )


def _record_transient(
    store: Store, backlink, *, status_code: int | None, detail: str | None,
) -> RecheckOutcome:
    """Bump attempts; if >= TRANSIENT_STRIKE_LIMIT, flip to dead/unreachable."""
    # We update status='live' with attempts_delta=+1 — `update_status`
    # treats positive delta as a bump-not-reset.
    update_status(store, backlink.id, backlink.status, attempts_delta=1)
    refreshed = store.get_backlink_attempts(backlink.id) if hasattr(
        store, "get_backlink_attempts"
    ) else _read_attempts(store, backlink.id)
    if refreshed >= TRANSIENT_STRIKE_LIMIT:
        update_status(store, backlink.id, "dead")
        return RecheckOutcome(
            backlink_id=backlink.id, decision="dead",
            status_code=status_code,
            detail=f"unreachable after {refreshed} attempts ({detail or ''})",
        )
    return RecheckOutcome(
        backlink_id=backlink.id, decision="transient",
        status_code=status_code, detail=detail,
    )


def _read_attempts(store: Store, backlink_id: int) -> int:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT recheck_attempts FROM backlinks WHERE id = ?",
            (backlink_id,),
        ).fetchone()
    return int(row["recheck_attempts"]) if row else 0


def summarize(outcomes: list[RecheckOutcome]) -> dict[str, int]:
    out: dict[str, int] = {}
    for o in outcomes:
        out[o.decision] = out.get(o.decision, 0) + 1
    return out


__all__ = ["recheck_all", "summarize"]
