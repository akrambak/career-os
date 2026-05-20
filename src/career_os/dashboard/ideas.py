"""Ideas persistence layer for the dashboard. UI-free so it's importable
and testable without streamlit. Ideas are raw seed jottings — title, hook,
target channel. Independent from posts (no promote-flow)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from ..db import Store

CHANNELS = ("blog", "linkedin", "x", "devto", "medium", "hn", "project")


@dataclass(frozen=True)
class Idea:
    id: int
    title: str
    hook: str | None
    channel: str
    tags: list[str]
    notes: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime


def _now() -> str:
    return datetime.now(UTC).isoformat()


def list_ideas(
    store: Store, channel: str | None = None, include_archived: bool = False
) -> list[Idea]:
    sql = "SELECT * FROM ideas WHERE 1=1"
    params: list = []
    if channel:
        sql += " AND channel = ?"
        params.append(channel)
    if not include_archived:
        sql += " AND archived = 0"
    sql += " ORDER BY updated_at DESC, id DESC"
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(sql, tuple(params)).fetchall()
    return [_row_to_idea(r) for r in rows]


def add_idea(
    store: Store, title: str, hook: str | None = None,
    channel: str = "blog", tags: list[str] | None = None,
    notes: str | None = None,
) -> Idea:
    if not title.strip():
        raise ValueError("title is required")
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}, expected one of {CHANNELS}")
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            """
            INSERT INTO ideas (title, hook, channel, tags, notes,
                               archived, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (title.strip(), hook, channel, json.dumps(tags or []), notes, now, now),
        )
        idea_id = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return _get(store, idea_id)


def update_idea(
    store: Store, idea_id: int, *,
    title: str | None = None, hook: str | None = None,
    channel: str | None = None, tags: list[str] | None = None,
    notes: str | None = None,
) -> Idea:
    fields: list[str] = []
    params: list = []
    if title is not None:
        if not title.strip():
            raise ValueError("title cannot be blank")
        fields.append("title=?")
        params.append(title.strip())
    if hook is not None:
        fields.append("hook=?")
        params.append(hook)
    if channel is not None:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}")
        fields.append("channel=?")
        params.append(channel)
    if tags is not None:
        fields.append("tags=?")
        params.append(json.dumps(tags))
    if notes is not None:
        fields.append("notes=?")
        params.append(notes)
    if not fields:
        return _get(store, idea_id)
    fields.append("updated_at=?")
    params.append(_now())
    params.append(idea_id)
    with store._conn() as c:  # noqa: SLF001
        c.execute(f"UPDATE ideas SET {', '.join(fields)} WHERE id=?", tuple(params))
    return _get(store, idea_id)


def archive(store: Store, idea_id: int, archived: bool = True) -> Idea:
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE ideas SET archived=?, updated_at=? WHERE id=?",
            (1 if archived else 0, _now(), idea_id),
        )
    return _get(store, idea_id)


def delete_idea(store: Store, idea_id: int) -> bool:
    with store._conn() as c:  # noqa: SLF001
        cur = c.execute("DELETE FROM ideas WHERE id=?", (idea_id,))
        return cur.rowcount > 0


def counts_by_channel(store: Store) -> dict[str, int]:
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT channel, COUNT(*) AS n FROM ideas "
            "WHERE archived=0 GROUP BY channel"
        ).fetchall()
    counts = {ch: 0 for ch in CHANNELS}
    for r in rows:
        counts[r["channel"]] = r["n"]
    return counts


def _get(store: Store, idea_id: int) -> Idea:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute("SELECT * FROM ideas WHERE id=?", (idea_id,)).fetchone()
    if row is None:
        raise LookupError(f"idea {idea_id} not found")
    return _row_to_idea(row)


def _row_to_idea(row) -> Idea:
    return Idea(
        id=row["id"],
        title=row["title"],
        hook=row["hook"],
        channel=row["channel"],
        tags=json.loads(row["tags"]),
        notes=row["notes"],
        archived=bool(row["archived"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


__all__ = [
    "Idea", "CHANNELS",
    "list_ideas", "add_idea", "update_idea",
    "archive", "delete_idea", "counts_by_channel",
]
