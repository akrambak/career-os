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
    # Tier 2 Upgrade 6: distinguish "0 new (source confirmed unchanged)"
    # from "0 new (failed)" from "0 new (just nothing happened to land)".
    last_status: str | None = None       # ok | unchanged | partial | failed | None (no watermark)
    last_fetched_at: datetime | None = None
    # Tier 3 Upgrade 8: number of postings flagged closed in the last 7 days.
    closed_7d: int = 0

    @property
    def status_display(self) -> str:
        """Human-friendly label for the dashboard."""
        if self.last_status == "unchanged":
            return "unchanged (304)"
        if self.last_status == "failed":
            return "failed"
        if self.last_status == "partial":
            return "partial"
        if self.last_status == "ok":
            return "ok"
        return "—"


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
    comp_min: float | None
    comp_max: float | None
    comp_currency: str | None
    comp_period: str | None
    suggested_angle: str | None
    has_draft: bool
    application_stage: str | None

    @property
    def comp_display(self) -> str:
        """Prefer the parsed structured form; fall back to the raw string."""
        if self.comp_min is not None or self.comp_max is not None:
            cur = self.comp_currency or ""
            lo = _fmt_amount(self.comp_min)
            hi = _fmt_amount(self.comp_max)
            period = f"/{self.comp_period}" if self.comp_period else ""
            if lo and hi and lo != hi:
                return f"{cur}{lo}–{hi}{period}".strip()
            return f"{cur}{lo or hi}{period}".strip()
        return self.compensation or "—"


def _fmt_amount(n: float | None) -> str:
    if n is None:
        return ""
    if n >= 1000:
        # 80000 → 80k; 80500 → 80.5k
        scaled = n / 1000.0
        return f"{scaled:.0f}k" if scaled == int(scaled) else f"{scaled:.1f}k"
    return f"{n:.0f}"


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
    closed_7d = store.closed_count_since(cutoff_7d)
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT
                j.source AS source,
                COUNT(*) AS total,
                SUM(CASE WHEN j.fetched_at >= ? THEN 1 ELSE 0 END) AS last_24h,
                SUM(CASE WHEN j.fetched_at >= ? THEN 1 ELSE 0 END) AS last_7d,
                MAX(j.fetched_at) AS most_recent,
                sw.last_status AS last_status,
                sw.last_fetched_at AS last_fetched_at
            FROM jobs j
            LEFT JOIN source_watermarks sw ON sw.source = j.source
            GROUP BY j.source
            ORDER BY last_24h DESC, j.source
            """,
            (cutoff_24h, cutoff_7d),
        ).fetchall()
    # Also include sources that have a watermark but no jobs yet (a fresh
    # scraper that returned 0). They'd otherwise be invisible.
    health_by_source = {
        r["source"]: SourceHealth(
            source=r["source"],
            last_24h=int(r["last_24h"] or 0),
            last_7d=int(r["last_7d"] or 0),
            total=int(r["total"] or 0),
            most_recent=datetime.fromisoformat(r["most_recent"]) if r["most_recent"] else None,
            last_status=r["last_status"],
            last_fetched_at=(
                datetime.fromisoformat(r["last_fetched_at"])
                if r["last_fetched_at"] else None
            ),
            closed_7d=closed_7d.get(r["source"], 0),
        )
        for r in rows
    }
    with store._conn() as c:  # noqa: SLF001
        wm_only = c.execute(
            """
            SELECT source, last_status, last_fetched_at
            FROM source_watermarks
            -- Only top-level keys here (no colon = no sub-feed suffix).
            WHERE source NOT LIKE '%:%'
            """,
        ).fetchall()
    for r in wm_only:
        if r["source"] in health_by_source:
            continue
        health_by_source[r["source"]] = SourceHealth(
            source=r["source"], last_24h=0, last_7d=0, total=0, most_recent=None,
            last_status=r["last_status"],
            last_fetched_at=(
                datetime.fromisoformat(r["last_fetched_at"])
                if r["last_fetched_at"] else None
            ),
            closed_7d=closed_7d.get(r["source"], 0),
        )
    return sorted(
        health_by_source.values(),
        key=lambda h: (-h.last_24h, h.source),
    )


def top_matches(
    store: Store, limit: int = 25, min_fit: int = 60, channel: str | None = None
) -> list[TopMatch]:
    sql = """
        SELECT j.key, s.fit, j.title, j.company, j.channel, j.source, j.url,
               j.compensation, j.comp_min, j.comp_max,
               j.comp_currency, j.comp_period,
               s.suggested_angle,
               (SELECT 1 FROM drafts d WHERE d.job_key = j.key) AS has_draft,
               (SELECT stage FROM applications a WHERE a.job_key = j.key) AS app_stage
        FROM jobs j JOIN scores s ON s.job_key = j.key
        WHERE s.fit >= ? AND j.is_closed = 0
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
            comp_min=r["comp_min"], comp_max=r["comp_max"],
            comp_currency=r["comp_currency"], comp_period=r["comp_period"],
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


def funnel(store: Store) -> dict[str, dict[str, int]]:
    """Per-channel funnel counts. {"ft": {stage: n, ...}, "freelance": {...}}.

    Tier 3 Upgrade 11: the FT and freelance pipelines have different middle
    stages and must be rendered separately. Use `flat_funnel()` if you
    really need a single combined view (e.g., a legacy total).
    """
    from ..tracker import funnel_counts
    return funnel_counts(store)


def flat_funnel(store: Store) -> dict[str, int]:
    """Back-compat: flat per-stage totals across channels. Used by older
    code paths that haven't been updated to render two funnels."""
    from ..tracker import flat_funnel_counts
    return flat_funnel_counts(store)


def totals(store: Store) -> dict[str, int]:
    with store._conn() as c:  # noqa: SLF001
        jobs = c.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"]
        scored = c.execute("SELECT COUNT(*) AS n FROM scores").fetchone()["n"]
        drafts = c.execute("SELECT COUNT(*) AS n FROM drafts").fetchone()["n"]
        apps = c.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"]
    return {"jobs": jobs, "scored": scored, "drafts": drafts, "applications": apps}
