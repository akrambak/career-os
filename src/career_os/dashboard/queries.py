"""Pure-data queries the dashboard renders. Kept separate from the Streamlit UI
so they can be tested without importing streamlit."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..db import Store


@dataclass(frozen=True)
class SourceHealth:
    source: str
    last_24h: int
    last_7d: int
    total: int
    most_recent: datetime | None


@dataclass(frozen=True)
class TopMatch:
    job_key: str
    fit: int
    title: str
    company: str | None
    channel: str
    source: str
    url: str
    compensation: str | None
    suggested_angle: str | None
    has_draft: bool
    application_stage: str | None


@dataclass(frozen=True)
class DraftReady:
    job_key: str
    fit: int
    title: str
    company: str | None
    channel: str
    drafted_at: datetime


def source_health(store: Store) -> list[SourceHealth]:
    cutoff_24h = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    cutoff_7d = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT
                source,
                COUNT(*) AS total,
                SUM(CASE WHEN fetched_at >= ? THEN 1 ELSE 0 END) AS last_24h,
                SUM(CASE WHEN fetched_at >= ? THEN 1 ELSE 0 END) AS last_7d,
                MAX(fetched_at) AS most_recent
            FROM jobs
            GROUP BY source
            ORDER BY last_24h DESC, source
            """,
            (cutoff_24h, cutoff_7d),
        ).fetchall()
    return [
        SourceHealth(
            source=r["source"],
            last_24h=int(r["last_24h"] or 0),
            last_7d=int(r["last_7d"] or 0),
            total=int(r["total"] or 0),
            most_recent=datetime.fromisoformat(r["most_recent"]) if r["most_recent"] else None,
        )
        for r in rows
    ]


def top_matches(
    store: Store, limit: int = 25, min_fit: int = 60, channel: str | None = None
) -> list[TopMatch]:
    sql = """
        SELECT j.key, s.fit, j.title, j.company, j.channel, j.source, j.url,
               j.compensation, s.suggested_angle,
               (SELECT 1 FROM drafts d WHERE d.job_key = j.key) AS has_draft,
               (SELECT stage FROM applications a WHERE a.job_key = j.key) AS app_stage
        FROM jobs j JOIN scores s ON s.job_key = j.key
        WHERE s.fit >= ?
    """
    params: list = [min_fit]
    if channel and channel != "all":
        sql += " AND j.channel = ?"
        params.append(channel)
    sql += " ORDER BY s.fit DESC, j.fetched_at DESC LIMIT ?"
    params.append(limit)
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(sql, tuple(params)).fetchall()
    return [
        TopMatch(
            job_key=r["key"], fit=int(r["fit"]), title=r["title"],
            company=r["company"], channel=r["channel"], source=r["source"],
            url=r["url"], compensation=r["compensation"],
            suggested_angle=r["suggested_angle"],
            has_draft=bool(r["has_draft"]),
            application_stage=r["app_stage"],
        )
        for r in rows
    ]


def drafts_ready(store: Store, limit: int = 20) -> list[DraftReady]:
    """Drafts that have been generated but no application has been recorded yet."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT d.job_key, d.drafted_at, j.title, j.company, j.channel,
                   COALESCE(s.fit, 0) AS fit
            FROM drafts d
            JOIN jobs j ON j.key = d.job_key
            LEFT JOIN scores s ON s.job_key = d.job_key
            LEFT JOIN applications a ON a.job_key = d.job_key
            WHERE a.job_key IS NULL
            ORDER BY s.fit DESC, d.drafted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        DraftReady(
            job_key=r["job_key"], fit=int(r["fit"]), title=r["title"],
            company=r["company"], channel=r["channel"],
            drafted_at=datetime.fromisoformat(r["drafted_at"]),
        )
        for r in rows
    ]


def funnel(store: Store) -> dict[str, int]:
    from ..tracker import STAGES, funnel_counts
    counts = funnel_counts(store)
    return {s: counts[s] for s in STAGES}


def totals(store: Store) -> dict[str, int]:
    with store._conn() as c:  # noqa: SLF001
        jobs = c.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        scored = c.execute("SELECT COUNT(*) AS n FROM scores").fetchone()["n"]
        drafts = c.execute("SELECT COUNT(*) AS n FROM drafts").fetchone()["n"]
        apps = c.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
    return {"jobs": jobs, "scored": scored, "drafts": drafts, "applications": apps}
