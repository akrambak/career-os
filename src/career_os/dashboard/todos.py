"""To-Do persistence layer for the dashboard. UI-free so it's importable
and testable without streamlit."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from ..db import Store
from .plan import DEFAULT_PLAN, SECTIONS, SeedItem


@dataclass(frozen=True)
class Todo:
    id: int
    section: str
    item: str
    notes: str | None
    priority: str
    due_date: date | None
    sort_order: int
    is_seed: bool
    checked: bool
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None

    @property
    def is_overdue(self) -> bool:
        if self.checked or self.due_date is None:
            return False
        return self.due_date < datetime.now(UTC).date()

    @property
    def days_until_due(self) -> int | None:
        if self.due_date is None:
            return None
        return (self.due_date - datetime.now(UTC).date()).days


def _now() -> str:
    return datetime.now(UTC).isoformat()


def seed_default_plan(store: Store) -> dict[str, int]:
    """Insert any new SeedItems, leave existing rows (checked + notes) alone.

    Returns a counts summary: {inserted, untouched}."""
    inserted = 0
    untouched = 0
    now = _now()
    section_order = {name: i for i, (name, _) in enumerate(SECTIONS)}

    with store._conn() as c:  # noqa: SLF001
        for sort_idx, seed in enumerate(DEFAULT_PLAN):
            existing = c.execute(
                "SELECT id FROM todos WHERE section = ? AND item = ?",
                (seed.section, seed.item),
            ).fetchone()
            if existing:
                untouched += 1
                continue
            order = section_order.get(seed.section, 999) * 1000 + sort_idx
            c.execute(
                """
                INSERT INTO todos (section, item, notes, priority, due_date,
                                   sort_order, is_seed, checked,
                                   created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
                """,
                (
                    seed.section, seed.item, seed.notes, seed.priority,
                    seed.due_date, order, now, now,
                ),
            )
            inserted += 1
    return {"inserted": inserted, "untouched": untouched}


def count_orphan_seeds(store: Store) -> int:
    """How many seeded rows in the DB are NOT in the current DEFAULT_PLAN.

    A non-zero count means plan.py was edited and the user should sync to
    drop the now-deleted seed items. Ad-hoc rows (is_seed=0) never count."""
    plan_keys = {(s.section, s.item) for s in DEFAULT_PLAN}
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT section, item FROM todos WHERE is_seed = 1"
        ).fetchall()
    return sum(1 for r in rows if (r["section"], r["item"]) not in plan_keys)


def sync_plan(store: Store) -> dict[str, int]:
    """Full reconciliation against current DEFAULT_PLAN.

    Three changes can happen:
      - new plan items are inserted
      - existing matching items get their priority/due_date/sort_order
        refreshed from the seed (checked state, notes, completed_at preserved)
      - seeded rows no longer in plan.py are DELETED

    Ad-hoc items (is_seed=0) are never touched. Returns counts."""
    now = _now()
    inserted = updated = removed = 0
    plan_keys = {(s.section, s.item) for s in DEFAULT_PLAN}
    section_order = {name: i for i, (name, _) in enumerate(SECTIONS)}

    with store._conn() as c:  # noqa: SLF001
        # 1. Remove orphan seeded rows
        existing = c.execute(
            "SELECT id, section, item FROM todos WHERE is_seed = 1"
        ).fetchall()
        for row in existing:
            if (row["section"], row["item"]) not in plan_keys:
                c.execute("DELETE FROM todos WHERE id = ?", (row["id"],))
                removed += 1

        # 2. Insert new + update metadata on matching items
        for sort_idx, seed in enumerate(DEFAULT_PLAN):
            order = section_order.get(seed.section, 999) * 1000 + sort_idx
            match = c.execute(
                "SELECT id FROM todos WHERE section = ? AND item = ?",
                (seed.section, seed.item),
            ).fetchone()
            if match:
                c.execute(
                    "UPDATE todos SET priority=?, due_date=?, sort_order=?, "
                    "is_seed=1, updated_at=? WHERE id=?",
                    (seed.priority, seed.due_date, order, now, match["id"]),
                )
                updated += 1
            else:
                c.execute(
                    """
                    INSERT INTO todos (section, item, notes, priority, due_date,
                                       sort_order, is_seed, checked,
                                       created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?)
                    """,
                    (seed.section, seed.item, seed.notes, seed.priority,
                     seed.due_date, order, now, now),
                )
                inserted += 1

    return {"inserted": inserted, "updated": updated, "removed": removed}


def list_todos(
    store: Store,
    section: str | None = None,
    open_only: bool = False,
    priority: str | None = None,
    query: str | None = None,
) -> list[Todo]:
    sql = "SELECT * FROM todos WHERE 1=1"
    params: list = []
    if section:
        sql += " AND section = ?"
        params.append(section)
    if open_only:
        sql += " AND checked = 0"
    if priority:
        sql += " AND priority = ?"
        params.append(priority)
    if query:
        sql += " AND (item LIKE ? OR COALESCE(notes,'') LIKE ?)"
        like = f"%{query}%"
        params += [like, like]
    sql += " ORDER BY sort_order, id"
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(sql, tuple(params)).fetchall()
    return [_row_to_todo(r) for r in rows]


def toggle(store: Store, todo_id: int, checked: bool) -> Todo:
    now = _now()
    completed_at = now if checked else None
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE todos SET checked=?, updated_at=?, completed_at=? WHERE id=?",
            (1 if checked else 0, now, completed_at, todo_id),
        )
    return _get(store, todo_id)


def update_notes(store: Store, todo_id: int, notes: str | None) -> Todo:
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE todos SET notes=?, updated_at=? WHERE id=?",
            (notes, _now(), todo_id),
        )
    return _get(store, todo_id)


def add_custom(
    store: Store, section: str, item: str,
    priority: str = "P1", due_date: str | None = None,
    notes: str | None = None,
) -> Todo:
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            """
            INSERT INTO todos (section, item, notes, priority, due_date,
                               sort_order, is_seed, checked,
                               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (section, item, notes, priority, due_date, 999_000, now, now),
        )
        todo_id = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return _get(store, todo_id)


def delete_todo(store: Store, todo_id: int) -> bool:
    with store._conn() as c:  # noqa: SLF001
        cur = c.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
        return cur.rowcount > 0


def section_progress(store: Store) -> dict[str, dict[str, int]]:
    """Per-section {total, done} counts in the order from SECTIONS."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT section, COUNT(*) AS total, SUM(checked) AS done "
            "FROM todos GROUP BY section"
        ).fetchall()
    by_section = {r["section"]: {"total": r["total"], "done": int(r["done"] or 0)} for r in rows}
    # Preserve canonical SECTIONS order; append any user-added sections at the end.
    ordered: dict[str, dict[str, int]] = {}
    for name, _ in SECTIONS:
        if name in by_section:
            ordered[name] = by_section.pop(name)
    for name, data in by_section.items():
        ordered[name] = data
    return ordered


def overall_progress(store: Store) -> tuple[int, int]:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT COUNT(*) AS total, SUM(checked) AS done FROM todos"
        ).fetchone()
    return int(row["done"] or 0), int(row["total"] or 0)


def todays_focus(store: Store, horizon_days: int = 7, limit: int = 8) -> list[Todo]:
    """P0 items due today/this week + any P0 with no due date that isn't checked."""
    from datetime import timedelta
    today_d = datetime.now(UTC).date()
    today = today_d.isoformat()
    horizon = (today_d + timedelta(days=horizon_days)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT * FROM todos
            WHERE checked = 0 AND priority = 'P0'
              AND (due_date IS NULL OR due_date <= ?)
              AND (due_date IS NULL OR due_date >= ?)
            ORDER BY
                CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
                due_date,
                sort_order
            LIMIT ?
            """,
            (horizon, today, limit),
        ).fetchall()
    return [_row_to_todo(r) for r in rows]


def _get(store: Store, todo_id: int) -> Todo:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    if row is None:
        raise LookupError(f"todo id {todo_id} not found")
    return _row_to_todo(row)


def _row_to_todo(row) -> Todo:
    return Todo(
        id=row["id"],
        section=row["section"],
        item=row["item"],
        notes=row["notes"],
        priority=row["priority"],
        due_date=date.fromisoformat(row["due_date"]) if row["due_date"] else None,
        sort_order=row["sort_order"],
        is_seed=bool(row["is_seed"]),
        checked=bool(row["checked"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
    )


__all__ = [
    "Todo", "SeedItem",
    "seed_default_plan", "sync_plan", "count_orphan_seeds",
    "list_todos", "toggle", "update_notes",
    "add_custom", "delete_todo",
    "section_progress", "overall_progress", "todays_focus",
]
