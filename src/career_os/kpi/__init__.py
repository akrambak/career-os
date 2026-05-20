"""KPI definitions + per-week snapshot persistence (Pillar 3).

A KPI is one row in a registry: `KPI(key, label, tier, source, threshold,
target_by_aug, decision_rule)`. Some are derived (we can read the value
from the other tables right now); the rest are manual entry.

Each Monday a snapshot is recorded per KPI. The dashboard then renders:
  - this-week value + status badge (green/red against decision_rule)
  - 28-day rolling trend (4 most-recent snapshots)
  - manual-entry form for the not-derivable ones

Decision rules from the user's plan (`docs/tier1-crawler-quality.md` and
the To-Do plan) become structured `Threshold` objects so the dashboard
can red/green automatically — not just display the number.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from ..db import Store


@dataclass(frozen=True)
class Threshold:
    """How to judge a value. `comparison` is 'gte' (at-or-above) for goal
    metrics like impressions; 'lte' for limit metrics like days-to-signed.
    A value that satisfies the comparison is GREEN."""
    comparison: str    # 'gte' | 'lte'
    bound: float

    def is_green(self, value: float) -> bool:
        if self.comparison == "gte":
            return value >= self.bound
        return value <= self.bound

    def display(self) -> str:
        sym = "≥" if self.comparison == "gte" else "≤"
        return f"{sym} {self.bound:g}"


@dataclass(frozen=True)
class KPI:
    key: str
    label: str
    tier: int                   # 1 (compounding) | 2 (conversion) | 3 (revenue)
    source: str                 # 'manual' | 'derived'
    threshold: Threshold | None
    unit: str = ""
    note: str = ""


# ---- the registry --------------------------------------------------------

# Drawn from README success metrics + To-Do plan decision rules.
KPIS: tuple[KPI, ...] = (
    # Tier 1 — compounding career assets
    KPI(
        "qualified_inbounds_wk", "Qualified inbounds / wk",
        tier=1, source="manual",
        threshold=Threshold("gte", 5), unit="leads",
        note="DMs / emails / scope calls landed this week.",
    ),
    KPI(
        "cold_reply_rate", "Cold reply rate",
        tier=1, source="manual",
        threshold=Threshold("gte", 0.12), unit="%",
        note="Replies / outreach sent. Aim 12%+ — below means positioning misaligned.",
    ),
    KPI(
        "linkedin_impressions_28d", "LinkedIn impressions (28d)",
        tier=1, source="manual",
        threshold=Threshold("gte", 50_000), unit="views",
        note="From LinkedIn analytics. Target 50k by Aug 8.",
    ),
    KPI(
        "github_stars", "GitHub stars (career-os repo)",
        tier=1, source="manual",
        threshold=Threshold("gte", 50), unit="stars",
        note="On github.com/akrambak/career-os. Target 50 by Aug 8.",
    ),
    KPI(
        "devto_avg_read_min", "dev.to avg read time / post",
        tier=1, source="manual",
        threshold=Threshold("gte", 3), unit="min",
        note="3min+ = the post landed beyond the title.",
    ),

    # Tier 2 — conversion
    KPI(
        "outreach_sent_wk", "Outreach sent / wk",
        tier=2, source="derived",
        threshold=Threshold("gte", 30), unit="msgs",
        note="<30 = not doing the work. Auto-counted from applications.",
    ),
    KPI(
        "calls_booked_wk", "Scope calls / interviews / wk",
        tier=2, source="derived",
        threshold=Threshold("gte", 2), unit="calls",
        note="From applications at stage scope_call / interview this week.",
    ),
    KPI(
        "call_to_proposal_pct", "Call → proposal %",
        tier=2, source="manual",
        threshold=Threshold("gte", 0.40), unit="%",
        note="<40% = the call shape is wrong; revisit qualifying questions.",
    ),
    KPI(
        "proposal_to_signed_pct", "Proposal → signed %",
        tier=2, source="manual",
        threshold=Threshold("gte", 0.30), unit="%",
        note="<30% = price or scope is wrong.",
    ),
    KPI(
        "first_contact_to_signed_days", "First contact → signed (days)",
        tier=2, source="manual",
        threshold=Threshold("lte", 35), unit="days",
        note=">35 = drop the lead; cycle is too long for the runway.",
    ),

    # Tier 3 — revenue
    KPI(
        "pipeline_value_eur", "Pipeline value (weighted, EUR)",
        tier=3, source="manual",
        threshold=Threshold("gte", 20_000), unit="EUR",
        note="Σ (proposal_value × stage_weight). 20k by wk 6.",
    ),
    KPI(
        "mrr_committed_eur", "MRR committed (EUR)",
        tier=3, source="manual",
        threshold=Threshold("gte", 3_000), unit="EUR",
        note="Signed retainers paying monthly. 3k by wk 10.",
    ),
    KPI(
        "runway_days_signed", "Runway days from signed work",
        tier=3, source="manual",
        threshold=Threshold("gte", 90), unit="days",
        note="Cash-on-hand + signed contracts ÷ burn rate. 90 by wk 12.",
    ),
)

KPIS_BY_KEY: dict[str, KPI] = {k.key: k for k in KPIS}


# ---- derived KPI compute helpers ----------------------------------------

def _monday_of_week(when: date | None = None) -> date:
    d = when or datetime.now(UTC).date()
    return d - timedelta(days=d.weekday())


def compute_derived(store: Store, week_start: date | None = None) -> dict[str, float]:
    """Return the values for every KPI with source='derived' for the given
    week. Returns a dict {kpi_key: value}."""
    mon = _monday_of_week(week_start)
    week_end = mon + timedelta(days=7)
    out: dict[str, float] = {}

    with store._conn() as c:  # noqa: SLF001
        # outreach_sent_wk — count applications recorded in [Monday, Monday+7).
        row = c.execute(
            "SELECT COUNT(*) AS n FROM applications "
            "WHERE applied_at >= ? AND applied_at < ?",
            (mon.isoformat(), week_end.isoformat()),
        ).fetchone()
        out["outreach_sent_wk"] = float(row["n"])

        # calls_booked_wk — applications whose CURRENT stage is scope_call /
        # interview and which transitioned this week (we approximate via
        # updated_at).
        row = c.execute(
            "SELECT COUNT(*) AS n FROM applications "
            "WHERE stage IN ('scope_call','interview') "
            "AND updated_at >= ? AND updated_at < ?",
            (mon.isoformat(), week_end.isoformat()),
        ).fetchone()
        out["calls_booked_wk"] = float(row["n"])
    return out


# ---- CRUD ----------------------------------------------------------------

@dataclass(frozen=True)
class Snapshot:
    id: int
    week_start: date
    kpi_key: str
    value: float
    target: float | None
    source: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


def upsert_snapshot(
    store: Store, *, kpi_key: str, value: float,
    week_start: date | None = None, target: float | None = None,
    source: str = "manual", notes: str | None = None,
) -> Snapshot:
    if kpi_key not in KPIS_BY_KEY:
        raise ValueError(f"unknown kpi {kpi_key!r}")
    mon = _monday_of_week(week_start)
    now = datetime.now(UTC).isoformat()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            """
            INSERT INTO kpi_snapshots
                (week_start, kpi_key, value, target, source, notes,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(week_start, kpi_key) DO UPDATE SET
                value=excluded.value,
                target=COALESCE(excluded.target, kpi_snapshots.target),
                source=excluded.source,
                notes=COALESCE(excluded.notes, kpi_snapshots.notes),
                updated_at=excluded.updated_at
            """,
            (mon.isoformat(), kpi_key, float(value), target, source, notes,
             now, now),
        )
    snap = get_snapshot(store, kpi_key, mon)
    assert snap is not None
    return snap


def get_snapshot(
    store: Store, kpi_key: str, week_start: date,
) -> Snapshot | None:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT * FROM kpi_snapshots WHERE kpi_key = ? AND week_start = ?",
            (kpi_key, week_start.isoformat()),
        ).fetchone()
    return _row_to_snapshot(row) if row else None


def list_recent(store: Store, kpi_key: str, weeks: int = 8) -> list[Snapshot]:
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT * FROM kpi_snapshots WHERE kpi_key = ? "
            "ORDER BY week_start DESC LIMIT ?",
            (kpi_key, weeks),
        ).fetchall()
    return [_row_to_snapshot(r) for r in rows]


def sync_derived(store: Store, week_start: date | None = None) -> int:
    """Recompute every derived KPI for the given week and upsert. Returns
    count of snapshots written."""
    derived = compute_derived(store, week_start)
    n = 0
    for kpi_key, value in derived.items():
        upsert_snapshot(
            store, kpi_key=kpi_key, value=value,
            week_start=week_start, source="derived",
        )
        n += 1
    return n


def _row_to_snapshot(row) -> Snapshot:
    return Snapshot(
        id=row["id"],
        week_start=date.fromisoformat(row["week_start"]),
        kpi_key=row["kpi_key"],
        value=float(row["value"]),
        target=float(row["target"]) if row["target"] is not None else None,
        source=row["source"],
        notes=row["notes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


__all__ = [
    "KPI", "Threshold", "Snapshot",
    "KPIS", "KPIS_BY_KEY",
    "compute_derived", "upsert_snapshot", "get_snapshot",
    "list_recent", "sync_derived",
]


# Convenience callable for the automations registry — auto-fill derived
# KPIs each week. Importing late to avoid circular dep.
def _ensure_automation_handler_registered() -> None:
    from .. import automations

    if "sync_derived_kpis" in automations.known_kinds():
        return

    @automations.register_handler("sync_derived_kpis")
    def _h_kpi_sync(store: Store, config: dict) -> automations.HandlerResult:
        n = sync_derived(store)
        return automations.HandlerResult("ok", f"synced {n} derived KPI(s)")


_ensure_automation_handler_registered()
