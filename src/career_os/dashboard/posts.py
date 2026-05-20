"""Posts persistence layer for the dashboard. UI-free so it's importable
and testable without streamlit. Posts are drafts being shaped toward
publish — independent from ideas (no promote-flow)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..db import Store

CHANNELS = ("blog", "linkedin", "x", "devto", "medium", "hn")
STATUSES = ("drafting", "ready", "posted")


@dataclass(frozen=True)
class Post:
    id: int
    title: str
    channel: str
    status: str
    body: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
    posted_at: datetime | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def list_posts(
    store: Store, status: str | None = None, channel: str | None = None
) -> list[Post]:
    sql = "SELECT * FROM posts WHERE 1=1"
    params: list = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if channel:
        sql += " AND channel=?"
        params.append(channel)
    sql += " ORDER BY updated_at DESC, id DESC"
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(sql, tuple(params)).fetchall()
    return [_row_to_post(r) for r in rows]


def add_post(
    store: Store, title: str, channel: str = "blog",
    body: str = "", notes: str | None = None,
) -> Post:
    if not title.strip():
        raise ValueError("title is required")
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}, expected one of {CHANNELS}")
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            """
            INSERT INTO posts (title, channel, status, body, notes,
                               created_at, updated_at)
            VALUES (?, ?, 'drafting', ?, ?, ?, ?)
            """,
            (title.strip(), channel, body, notes, now, now),
        )
        post_id = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return _get(store, post_id)


def update_post(
    store: Store, post_id: int, *,
    title: str | None = None, channel: str | None = None,
    body: str | None = None, notes: str | None = None,
) -> Post:
    fields: list[str] = []
    params: list = []
    if title is not None:
        if not title.strip():
            raise ValueError("title cannot be blank")
        fields.append("title=?")
        params.append(title.strip())
    if channel is not None:
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}")
        fields.append("channel=?")
        params.append(channel)
    if body is not None:
        fields.append("body=?")
        params.append(body)
    if notes is not None:
        fields.append("notes=?")
        params.append(notes)
    if not fields:
        return _get(store, post_id)
    fields.append("updated_at=?")
    params.append(_now())
    params.append(post_id)
    with store._conn() as c:  # noqa: SLF001
        c.execute(f"UPDATE posts SET {', '.join(fields)} WHERE id=?", tuple(params))
    return _get(store, post_id)


def set_status(store: Store, post_id: int, status: str) -> Post:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}, expected one of {STATUSES}")
    now = _now()
    posted_at_clause = ", posted_at=?" if status == "posted" else ""
    params: tuple = (status, now, post_id) if status != "posted" else (status, now, now, post_id)
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            f"UPDATE posts SET status=?, updated_at=?{posted_at_clause} WHERE id=?",
            params,
        )
    return _get(store, post_id)


def delete_post(store: Store, post_id: int) -> bool:
    with store._conn() as c:  # noqa: SLF001
        cur = c.execute("DELETE FROM posts WHERE id=?", (post_id,))
        return cur.rowcount > 0


def get_post(store: Store, post_id: int) -> Post | None:
    try:
        return _get(store, post_id)
    except LookupError:
        return None


def counts_by_status(store: Store) -> dict[str, int]:
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM posts GROUP BY status"
        ).fetchall()
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"]] = r["n"]
    return counts


def _get(store: Store, post_id: int) -> Post:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute("SELECT * FROM posts WHERE id=?", (post_id,)).fetchone()
    if row is None:
        raise LookupError(f"post {post_id} not found")
    return _row_to_post(row)


def _row_to_post(row) -> Post:
    return Post(
        id=row["id"],
        title=row["title"],
        channel=row["channel"],
        status=row["status"],
        body=row["body"],
        notes=row["notes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        posted_at=(
            datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None
        ),
    )


__all__ = [
    "Post", "CHANNELS", "STATUSES",
    "list_posts", "add_post", "update_post", "set_status",
    "delete_post", "get_post", "counts_by_status",
]
