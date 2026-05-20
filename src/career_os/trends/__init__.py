"""Trend feed — scraped public signals (HN, dev.to, Tavily web search) that
feed the post generator.

Data layer + signal scoring. Scrapers live in `.sources`; the Claude
generator in `.generator`. The dashboard page consumes everything here.

`signal_score = base × recency × topic_fit`. Re-computed on every upsert
so a trend climbing the frontpage rises in our feed within the same
minute we re-scan.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..db import Store
from ..models import Profile

SOURCES = ("hn", "devto", "reddit", "tavily", "manual")


@dataclass(frozen=True)
class Trend:
    id: int
    source: str
    external_id: str | None
    url: str
    title: str
    summary: str | None
    score: int
    comment_count: int
    tags: list[str]
    raw: dict
    signal_score: float
    fetched_at: datetime
    used_at: datetime | None


# ---- signal score --------------------------------------------------------

# How fast we decay. 168 hours = 7 days. Older than that → recency_factor = 0
# and the trend won't surface even if it had high engagement.
_RECENCY_HORIZON_HOURS = 168.0
_TOPIC_BONUS_PER_TERM = 0.3
_TOPIC_FACTOR_CAP = 2.0


def compute_signal_score(
    *,
    score: int,
    comment_count: int,
    fetched_at: datetime | None,
    title: str,
    tags: list[str],
    profile: Profile | None = None,
) -> float:
    base = math.log10(1 + max(0, score)) + 0.5 * math.log10(1 + max(0, comment_count))
    recency = _recency_factor(fetched_at)
    topic = _topic_factor(title, tags, profile)
    return round(base * recency * topic, 4)


def _recency_factor(fetched_at: datetime | None) -> float:
    if fetched_at is None:
        return 1.0
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    age_hours = (datetime.now(UTC) - fetched_at).total_seconds() / 3600.0
    if age_hours <= 0:
        return 1.0
    if age_hours >= _RECENCY_HORIZON_HOURS:
        return 0.0
    return 1.0 - (age_hours / _RECENCY_HORIZON_HOURS)


def _topic_factor(
    title: str, tags: list[str], profile: Profile | None,
) -> float:
    if profile is None:
        return 1.0
    haystack = (title + " " + " ".join(tags)).lower()
    terms = set()
    for term in (*profile.proven_stack, *profile.new_stack):
        # Single-word match per stack term — split multi-word terms.
        for piece in term.replace("/", " ").split():
            if len(piece) > 2:
                terms.add(piece.lower())
    hits = sum(1 for t in terms if t in haystack)
    factor = 1.0 + _TOPIC_BONUS_PER_TERM * hits
    return min(_TOPIC_FACTOR_CAP, factor)


# ---- CRUD ----------------------------------------------------------------

def upsert_trend(
    store: Store, *,
    source: str, url: str, title: str,
    external_id: str | None = None,
    summary: str | None = None,
    score: int = 0, comment_count: int = 0,
    tags: list[str] | None = None,
    raw: dict | None = None,
    fetched_at: datetime | None = None,
    profile: Profile | None = None,
) -> Trend:
    """Idempotent insert keyed on (source, external_id). Existing rows are
    refreshed (score/comments climb, signal_score recomputes). New rows
    are created with fetched_at = NOW unless explicitly given.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    fetched = (fetched_at or datetime.now(UTC))
    signal = compute_signal_score(
        score=score, comment_count=comment_count,
        fetched_at=fetched,
        title=title, tags=tags or [],
        profile=profile,
    )
    raw_json = json.dumps(raw or {})
    tags_json = json.dumps(tags or [])
    with store._conn() as c:  # noqa: SLF001
        existing = c.execute(
            "SELECT id FROM trends WHERE source = ? AND external_id IS ?",
            (source, external_id),
        ).fetchone()
        if existing:
            c.execute(
                """
                UPDATE trends SET
                    url=?, title=?, summary=?, score=?, comment_count=?,
                    tags=?, raw=?, signal_score=?
                WHERE id=?
                """,
                (url, title, summary, score, comment_count,
                 tags_json, raw_json, signal, existing["id"]),
            )
            trend_id = existing["id"]
        else:
            c.execute(
                """
                INSERT INTO trends (
                    source, external_id, url, title, summary, score,
                    comment_count, tags, raw, signal_score, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source, external_id, url, title, summary, score,
                 comment_count, tags_json, raw_json, signal,
                 fetched.isoformat()),
            )
            trend_id = c.execute(
                "SELECT last_insert_rowid() AS id"
            ).fetchone()["id"]
    return get_trend(store, trend_id)


def get_trend(store: Store, trend_id: int) -> Trend:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT * FROM trends WHERE id = ?", (trend_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"trend {trend_id} not found")
    return _row_to_trend(row)


def list_trends(
    store: Store, *,
    source: str | None = None,
    min_signal: float = 0.0,
    hide_used: bool = True,
    limit: int = 50,
) -> list[Trend]:
    sql = "SELECT * FROM trends WHERE signal_score >= ?"
    params: list = [min_signal]
    if source:
        sql += " AND source = ?"
        params.append(source)
    if hide_used:
        sql += " AND used_at IS NULL"
    sql += " ORDER BY signal_score DESC, fetched_at DESC LIMIT ?"
    params.append(limit)
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(sql, tuple(params)).fetchall()
    return [_row_to_trend(r) for r in rows]


def mark_used(store: Store, trend_id: int) -> Trend:
    """Set used_at to NOW. Idempotent — preserves the original used_at
    on subsequent calls."""
    now = datetime.now(UTC).isoformat()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE trends SET used_at = COALESCE(used_at, ?) WHERE id = ?",
            (now, trend_id),
        )
    return get_trend(store, trend_id)


def counts_by_source(store: Store) -> dict[str, int]:
    """Per-source counts for the dashboard header."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT source, COUNT(*) AS n FROM trends GROUP BY source",
        ).fetchall()
    counts = {s: 0 for s in SOURCES}
    for r in rows:
        counts[r["source"]] = int(r["n"])
    return counts


def recompute_all_signals(
    store: Store, profile: Profile | None = None,
) -> int:
    """Walk every trend, recompute signal_score with current recency.
    Useful after a `profile.py` edit or to demote stale rows. Returns
    rows updated."""
    n = 0
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute("SELECT * FROM trends").fetchall()
        for row in rows:
            fetched = datetime.fromisoformat(row["fetched_at"])
            sig = compute_signal_score(
                score=int(row["score"]),
                comment_count=int(row["comment_count"]),
                fetched_at=fetched,
                title=row["title"],
                tags=json.loads(row["tags"] or "[]"),
                profile=profile,
            )
            c.execute(
                "UPDATE trends SET signal_score = ? WHERE id = ?",
                (sig, row["id"]),
            )
            n += 1
    return n


def purge_old(store: Store, older_than_days: int = 30) -> int:
    """Delete trends older than N days that have NOT been used. Keeps used
    trends as breadcrumbs to their posts."""
    cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        cur = c.execute(
            "DELETE FROM trends WHERE fetched_at < ? AND used_at IS NULL",
            (cutoff,),
        )
        return cur.rowcount


def _row_to_trend(row) -> Trend:
    return Trend(
        id=int(row["id"]),
        source=row["source"],
        external_id=row["external_id"],
        url=row["url"],
        title=row["title"],
        summary=row["summary"],
        score=int(row["score"] or 0),
        comment_count=int(row["comment_count"] or 0),
        tags=json.loads(row["tags"] or "[]"),
        raw=json.loads(row["raw"] or "{}"),
        signal_score=float(row["signal_score"] or 0.0),
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
        used_at=(
            datetime.fromisoformat(row["used_at"]) if row["used_at"] else None
        ),
    )


__all__ = [
    "SOURCES", "Trend",
    "compute_signal_score",
    "upsert_trend", "get_trend", "list_trends", "mark_used",
    "counts_by_source", "recompute_all_signals", "purge_old",
]
