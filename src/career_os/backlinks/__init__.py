"""Backlinks inventory + weekly health checks (SEO Feature 1).

Stores every external page linking TO our domain(s) / repo / content.
Health checks (`recheck_all`) walk each row, fetch the source_url, and
classify status:

  - 200 + target URL in body  → status='live'
  - 200 + target URL absent   → status='removed' (page lives, link gone)
  - 3xx redirect              → status='redirect'
  - 404/410                   → status='dead'
  - 5xx / network             → bump attempts; 3 strikes → status='dead'

A status flip from live → dead/removed is what the Inbox action
generator listens for. Once detected, the user can reach out to the
publisher or look up the new URL.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from ..db import Store

logger = logging.getLogger(__name__)

REL_VALUES = ("dofollow", "nofollow", "ugc", "sponsored")
STATUSES = ("live", "dead", "redirect", "removed", "unverified")
TRANSIENT_STRIKE_LIMIT = 3


@dataclass(frozen=True)
class Backlink:
    id: int
    source_url: str
    source_domain: str
    target_url: str
    anchor_text: str | None
    rel: str
    status: str
    da_estimate: int | None
    discovered_via: str
    first_seen_at: datetime
    last_checked_at: datetime | None
    recheck_attempts: int
    notes: str | None


# ---- CRUD ----------------------------------------------------------------

def _now() -> str:
    return datetime.now(UTC).isoformat()


def _domain_of(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        # Strip 'www.' so the same root domain doesn't fragment counts.
        return host[4:] if host.startswith("www.") else host
    except (ValueError, AttributeError):
        return ""


def upsert_backlink(
    store: Store, *,
    source_url: str, target_url: str,
    anchor_text: str | None = None, rel: str = "dofollow",
    status: str = "live", da_estimate: int | None = None,
    discovered_via: str = "manual", notes: str | None = None,
) -> Backlink:
    """Idempotent on (source_url, target_url). Refreshes anchor + rel +
    status; preserves first_seen_at."""
    if rel not in REL_VALUES:
        raise ValueError(f"rel must be one of {REL_VALUES}, got {rel!r}")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    source_domain = _domain_of(source_url)
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        existing = c.execute(
            "SELECT id FROM backlinks WHERE source_url = ? AND target_url = ?",
            (source_url, target_url),
        ).fetchone()
        if existing:
            c.execute(
                """
                UPDATE backlinks SET
                    source_domain=?, anchor_text=?, rel=?, status=?,
                    da_estimate=COALESCE(?, da_estimate),
                    notes=COALESCE(?, notes)
                WHERE id=?
                """,
                (source_domain, anchor_text, rel, status, da_estimate,
                 notes, existing["id"]),
            )
            backlink_id = existing["id"]
        else:
            c.execute(
                """
                INSERT INTO backlinks (
                    source_url, source_domain, target_url, anchor_text,
                    rel, status, da_estimate, discovered_via,
                    first_seen_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source_url, source_domain, target_url, anchor_text,
                 rel, status, da_estimate, discovered_via, now, notes),
            )
            backlink_id = c.execute(
                "SELECT last_insert_rowid() AS id"
            ).fetchone()["id"]
    return get_backlink(store, backlink_id)


def get_backlink(store: Store, backlink_id: int) -> Backlink:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT * FROM backlinks WHERE id = ?", (backlink_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"backlink {backlink_id} not found")
    return _row_to_backlink(row)


def list_backlinks(
    store: Store, *,
    status: str | None = None,
    rel: str | None = None,
    source_domain: str | None = None,
    min_da: int | None = None,
    limit: int = 200,
) -> list[Backlink]:
    sql_parts = ["SELECT * FROM backlinks WHERE 1=1"]
    params: list = []
    if status:
        sql_parts.append("AND status = ?")
        params.append(status)
    if rel:
        sql_parts.append("AND rel = ?")
        params.append(rel)
    if source_domain:
        sql_parts.append("AND source_domain = ?")
        params.append(source_domain)
    if min_da is not None:
        sql_parts.append("AND COALESCE(da_estimate, 0) >= ?")
        params.append(min_da)
    sql_parts.append("ORDER BY first_seen_at DESC LIMIT ?")
    params.append(limit)
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(" ".join(sql_parts), tuple(params)).fetchall()
    return [_row_to_backlink(r) for r in rows]


def delete_backlink(store: Store, backlink_id: int) -> bool:
    with store._conn() as c:  # noqa: SLF001
        cur = c.execute("DELETE FROM backlinks WHERE id = ?", (backlink_id,))
        return cur.rowcount > 0


def update_status(
    store: Store, backlink_id: int, status: str,
    *, attempts_delta: int = 0,
) -> Backlink:
    """Set status + last_checked_at. `attempts_delta=+1` for transient
    failures; `=0` clears via `update_status(..., status='live')`."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        if attempts_delta > 0:
            c.execute(
                "UPDATE backlinks SET status=?, last_checked_at=?, "
                "recheck_attempts=recheck_attempts + ? WHERE id=?",
                (status, now, attempts_delta, backlink_id),
            )
        else:
            c.execute(
                "UPDATE backlinks SET status=?, last_checked_at=?, "
                "recheck_attempts=0 WHERE id=?",
                (status, now, backlink_id),
            )
    return get_backlink(store, backlink_id)


def update_rel(store: Store, backlink_id: int, rel: str) -> Backlink:
    if rel not in REL_VALUES:
        raise ValueError(f"rel must be one of {REL_VALUES}")
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE backlinks SET rel=? WHERE id=?",
            (rel, backlink_id),
        )
    return get_backlink(store, backlink_id)


# ---- aggregates for the dashboard ---------------------------------------

def counts_by_status(store: Store) -> dict[str, int]:
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM backlinks GROUP BY status",
        ).fetchall()
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"]] = int(r["n"])
    return counts


def dofollow_ratio(store: Store) -> float:
    """Fraction of LIVE backlinks that are dofollow. 0.0 if no live links."""
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT "
            "  SUM(CASE WHEN rel = 'dofollow' THEN 1 ELSE 0 END) AS dofollow, "
            "  COUNT(*) AS total "
            "FROM backlinks WHERE status = 'live'",
        ).fetchone()
    total = int(row["total"] or 0)
    if total == 0:
        return 0.0
    return round(int(row["dofollow"] or 0) / total, 4)


def unique_referring_domains(store: Store) -> int:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT COUNT(DISTINCT source_domain) AS n FROM backlinks "
            "WHERE status = 'live'",
        ).fetchone()
    return int(row["n"] or 0)


# ---- recheck driver (uses generic decision pattern) ---------------------

@dataclass(frozen=True)
class RecheckOutcome:
    backlink_id: int
    decision: str          # 'live' | 'dead' | 'removed' | 'redirect' | 'transient'
    status_code: int | None
    detail: str | None


def candidates_for_recheck(
    store: Store, *, limit: int = 200, max_age_days: int = 7,
) -> list[Backlink]:
    """Live backlinks not rechecked in max_age_days. NULL last_checked_at
    counts as "never checked" (always due)."""
    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT * FROM backlinks WHERE status IN ('live', 'redirect') "
            "AND (last_checked_at IS NULL OR last_checked_at < ?) "
            "ORDER BY COALESCE(last_checked_at, '0000-00-00') ASC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
    return [_row_to_backlink(r) for r in rows]


def decide_from_response(
    *, target_url: str, status_code: int, body: str | None,
    final_url: str | None = None,
) -> tuple[str, str | None]:
    """Pure helper — given an HTTP response, decide the new backlink
    status. Returns (decision, detail). `decision` is the value that
    will be written to `status` (with `transient` mapped to a status
    bump by the caller).

    - 200 + body contains target_url → 'live'
    - 200 + body absent → 'removed' (the page exists, but our link is gone)
    - 3xx with final_url ≠ source → 'redirect' (still kinda alive)
    - 404/410 → 'dead'
    - 5xx / 4xx-other → 'transient' (caller bumps attempts)
    """
    if status_code in (404, 410):
        return ("dead", f"http {status_code}")
    if 500 <= status_code < 600:
        return ("transient", f"http {status_code}")
    if 400 <= status_code < 500:
        return ("transient", f"http {status_code}")
    if 300 <= status_code < 400:
        return ("redirect", final_url or "redirect")
    if status_code == 200:
        if body and _body_contains_url(body, target_url):
            return ("live", None)
        return ("removed", "target URL absent from rendered body")
    return ("transient", f"unexpected http {status_code}")


def _body_contains_url(body: str, target_url: str) -> bool:
    """Substring match with light normalization — handles http/https
    swaps and trailing-slash differences."""
    if not body:
        return False
    haystack = body
    needle = target_url.strip()
    # try the literal first
    if needle in haystack:
        return True
    # http ↔ https
    if needle.startswith("https://"):
        alt = "http://" + needle[len("https://"):]
    elif needle.startswith("http://"):
        alt = "https://" + needle[len("http://"):]
    else:
        alt = needle
    if alt and alt in haystack:
        return True
    # trim trailing slash
    return bool(needle.endswith("/") and needle.rstrip("/") in haystack)


def detect_rel(body: str, target_url: str) -> str | None:
    """Best-effort: find `<a href="<target_url>" ... rel="...">` and
    classify. Returns None if no anchor referencing the target was
    found."""
    if not body:
        return None
    target_re = re.escape(target_url)
    pattern = re.compile(
        rf"<a\s[^>]*href=[\"']{target_re}[\"'][^>]*>",
        re.IGNORECASE,
    )
    m = pattern.search(body)
    if not m:
        # Try with trailing-slash variant
        if target_url.endswith("/"):
            return detect_rel(body, target_url.rstrip("/"))
        return None
    anchor = m.group(0)
    rel_match = re.search(r"rel=[\"']([^\"']+)[\"']", anchor, re.IGNORECASE)
    if not rel_match:
        return "dofollow"
    rels = {v.strip().lower() for v in rel_match.group(1).split()}
    if "sponsored" in rels:
        return "sponsored"
    if "ugc" in rels:
        return "ugc"
    if "nofollow" in rels:
        return "nofollow"
    return "dofollow"


# ---- internals ----------------------------------------------------------

def _row_to_backlink(row) -> Backlink:
    return Backlink(
        id=int(row["id"]),
        source_url=row["source_url"],
        source_domain=row["source_domain"] or "",
        target_url=row["target_url"],
        anchor_text=row["anchor_text"],
        rel=row["rel"],
        status=row["status"],
        da_estimate=int(row["da_estimate"]) if row["da_estimate"] is not None else None,
        discovered_via=row["discovered_via"],
        first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
        last_checked_at=(
            datetime.fromisoformat(row["last_checked_at"])
            if row["last_checked_at"] else None
        ),
        recheck_attempts=int(row["recheck_attempts"] or 0),
        notes=row["notes"],
    )


__all__ = [
    "REL_VALUES", "STATUSES", "TRANSIENT_STRIKE_LIMIT",
    "Backlink", "RecheckOutcome",
    "upsert_backlink", "get_backlink", "list_backlinks",
    "delete_backlink", "update_status", "update_rel",
    "counts_by_status", "dofollow_ratio", "unique_referring_domains",
    "candidates_for_recheck", "decide_from_response",
    "detect_rel",
]
