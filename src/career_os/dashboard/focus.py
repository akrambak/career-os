"""Today's focus — aggregate the most important things across pages
into one banner shown at the top of Overview. UI-free so it can be
unit-tested without streamlit."""
from __future__ import annotations

from dataclasses import dataclass

from ..actions import counts_by_severity
from ..db import Store


@dataclass(frozen=True)
class FocusSummary:
    urgent_actions: int
    normal_actions: int
    low_actions: int
    p0_todos_due_week: int
    posts_ready_to_publish: int
    stale_applications: int

    @property
    def total_actions(self) -> int:
        return self.urgent_actions + self.normal_actions + self.low_actions

    @property
    def headline(self) -> str:
        """One-line summary for the banner header."""
        if self.urgent_actions > 0:
            return f"🔴 {self.urgent_actions} urgent · {self.total_actions} total in inbox"
        if self.total_actions > 0:
            return f"🟡 {self.total_actions} actions waiting in inbox"
        if self.p0_todos_due_week > 0:
            return f"⚡ {self.p0_todos_due_week} P0 todos due this week"
        return "🟢 Inbox zero — ship something visible today"


def compute_focus(store: Store) -> FocusSummary:
    sev = counts_by_severity(store)
    return FocusSummary(
        urgent_actions=sev.get("urgent", 0),
        normal_actions=sev.get("normal", 0),
        low_actions=sev.get("low", 0),
        p0_todos_due_week=_p0_todos_due_week(store),
        posts_ready_to_publish=_posts_ready_count(store),
        stale_applications=_stale_apps_count(store),
    )


def _p0_todos_due_week(store: Store) -> int:
    from datetime import UTC, datetime, timedelta
    horizon = (datetime.now(UTC).date() + timedelta(days=7)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT COUNT(*) AS n FROM todos "
            "WHERE checked = 0 AND priority = 'P0' "
            "AND (due_date IS NULL OR due_date <= ?)",
            (horizon,),
        ).fetchone()
    return int(row["n"] or 0)


def _posts_ready_count(store: Store) -> int:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT COUNT(*) AS n FROM posts "
            "WHERE status = 'ready' AND posted_at IS NULL",
        ).fetchone()
    return int(row["n"] or 0)


def _stale_apps_count(store: Store, days: int = 7) -> int:
    from datetime import UTC, datetime, timedelta
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT COUNT(*) AS n FROM applications "
            "WHERE stage NOT IN ('won','rejected','dropped') "
            "AND updated_at < ?",
            (cutoff,),
        ).fetchone()
    return int(row["n"] or 0)


__all__ = ["FocusSummary", "compute_focus"]
