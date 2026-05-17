from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path

from ..models import Channel, JobPost, Score

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    key             TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    external_id     TEXT NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT NOT NULL,
    company         TEXT,
    location        TEXT,
    description     TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    channel         TEXT NOT NULL,
    compensation    TEXT,
    posted_at       TEXT,
    fetched_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_channel ON jobs(channel);
CREATE INDEX IF NOT EXISTS idx_jobs_fetched_at ON jobs(fetched_at);

CREATE TABLE IF NOT EXISTS scores (
    job_key         TEXT PRIMARY KEY REFERENCES jobs(key) ON DELETE CASCADE,
    fit             INTEGER NOT NULL,
    reasoning       TEXT NOT NULL,
    pros            TEXT NOT NULL DEFAULT '[]',
    cons            TEXT NOT NULL DEFAULT '[]',
    suggested_angle TEXT,
    scored_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scores_fit ON scores(fit DESC);

CREATE TABLE IF NOT EXISTS applications (
    job_key         TEXT PRIMARY KEY REFERENCES jobs(key) ON DELETE CASCADE,
    stage           TEXT NOT NULL,
    notes           TEXT,
    applied_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS drafts (
    job_key         TEXT PRIMARY KEY REFERENCES jobs(key) ON DELETE CASCADE,
    format          TEXT NOT NULL,
    subject         TEXT,
    body            TEXT NOT NULL,
    model           TEXT NOT NULL,
    drafted_at      TEXT NOT NULL
);

-- The To-Do / Plan page persists the user's progress against the seeded
-- 12-week plan (and any ad-hoc items they add). (section, item) is unique
-- so the seeder can be idempotent — re-running it never clobbers state.
CREATE TABLE IF NOT EXISTS todos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    section       TEXT NOT NULL,
    item          TEXT NOT NULL,
    notes         TEXT,
    priority      TEXT NOT NULL DEFAULT 'P2',
    due_date      TEXT,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    is_seed       INTEGER NOT NULL DEFAULT 0,
    checked       INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    completed_at  TEXT,
    UNIQUE(section, item)
);

CREATE INDEX IF NOT EXISTS idx_todos_section ON todos(section);
CREATE INDEX IF NOT EXISTS idx_todos_checked ON todos(checked);
CREATE INDEX IF NOT EXISTS idx_todos_due_date ON todos(due_date);
"""


class Store:
    def __init__(self, db_url: str):
        if not db_url.startswith("sqlite:///"):
            raise ValueError(
                f"Only sqlite:/// is supported in MVP, got {db_url!r}. "
                "Postgres support lands in Phase 2."
            )
        path = Path(db_url.removeprefix("sqlite:///"))
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_job(self, job: JobPost) -> bool:
        with self._conn() as c:
            cursor = c.execute("SELECT 1 FROM jobs WHERE key = ?", (job.key,))
            exists = cursor.fetchone() is not None
            c.execute(
                """
                INSERT INTO jobs (key, source, external_id, url, title, company,
                                  location, description, tags, channel,
                                  compensation, posted_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    title=excluded.title,
                    company=excluded.company,
                    location=excluded.location,
                    description=excluded.description,
                    tags=excluded.tags,
                    channel=excluded.channel,
                    compensation=excluded.compensation,
                    fetched_at=excluded.fetched_at
                """,
                (
                    job.key, job.source, job.external_id, str(job.url),
                    job.title, job.company, job.location, job.description,
                    json.dumps(job.tags), job.channel.value, job.compensation,
                    job.posted_at.isoformat() if job.posted_at else None,
                    job.fetched_at.isoformat(),
                ),
            )
            return not exists

    def unscored_jobs(self, limit: int = 50) -> list[JobPost]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT j.* FROM jobs j
                LEFT JOIN scores s ON s.job_key = j.key
                WHERE s.job_key IS NULL
                ORDER BY j.fetched_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def save_score(self, score: Score) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO scores (job_key, fit, reasoning, pros, cons,
                                    suggested_angle, scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_key) DO UPDATE SET
                    fit=excluded.fit,
                    reasoning=excluded.reasoning,
                    pros=excluded.pros,
                    cons=excluded.cons,
                    suggested_angle=excluded.suggested_angle,
                    scored_at=excluded.scored_at
                """,
                (
                    score.job_key, score.fit, score.reasoning,
                    json.dumps(score.pros), json.dumps(score.cons),
                    score.suggested_angle, score.scored_at.isoformat(),
                ),
            )

    def get_job(self, key: str) -> JobPost | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM jobs WHERE key = ?", (key,)).fetchone()
        return _row_to_job(row) if row else None

    def get_score(self, job_key: str) -> Score | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT key, fit, reasoning, pros, cons, suggested_angle, scored_at "
                "FROM jobs j JOIN scores s ON s.job_key = j.key WHERE j.key = ?",
                (job_key,),
            ).fetchone()
        return _row_to_score(row) if row else None

    def save_draft(
        self, job_key: str, fmt: str, body: str, model: str, subject: str | None = None
    ) -> None:
        from datetime import datetime
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO drafts (job_key, format, subject, body, model, drafted_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_key) DO UPDATE SET
                    format=excluded.format,
                    subject=excluded.subject,
                    body=excluded.body,
                    model=excluded.model,
                    drafted_at=excluded.drafted_at
                """,
                (job_key, fmt, subject, body, model,
                 datetime.now(UTC).isoformat()),
            )

    def get_draft(self, job_key: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT format, subject, body, model, drafted_at "
                "FROM drafts WHERE job_key = ?",
                (job_key,),
            ).fetchone()
        return dict(row) if row else None

    def top_scored(self, limit: int = 5, min_fit: int = 0) -> list[tuple[JobPost, Score]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT j.*, s.fit, s.reasoning, s.pros, s.cons,
                       s.suggested_angle, s.scored_at
                FROM jobs j JOIN scores s ON s.job_key = j.key
                WHERE s.fit >= ?
                ORDER BY s.fit DESC, j.fetched_at DESC
                LIMIT ?
                """,
                (min_fit, limit),
            ).fetchall()
        return [(_row_to_job(r), _row_to_score(r)) for r in rows]


def _row_to_job(row: sqlite3.Row) -> JobPost:
    from datetime import datetime
    return JobPost(
        source=row["source"],
        external_id=row["external_id"],
        url=row["url"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        description=row["description"],
        tags=json.loads(row["tags"]),
        channel=Channel(row["channel"]),
        compensation=row["compensation"],
        posted_at=datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None,
        fetched_at=datetime.fromisoformat(row["fetched_at"]),
    )


def _row_to_score(row: sqlite3.Row) -> Score:
    from datetime import datetime
    return Score(
        job_key=row["key"],
        fit=row["fit"],
        reasoning=row["reasoning"],
        pros=json.loads(row["pros"]),
        cons=json.loads(row["cons"]),
        suggested_angle=row["suggested_angle"],
        scored_at=datetime.fromisoformat(row["scored_at"]),
    )
