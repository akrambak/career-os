"""Additive schema migrations applied on every Store init.

The original `SCHEMA` block in `store.py` uses `CREATE TABLE IF NOT EXISTS`
which is idempotent but can't express `ALTER TABLE ADD COLUMN`. New columns
on existing tables go here.

Pattern: each migration is a small function that uses `_add_column_if_missing`
or executes its own DDL inside `IF NOT EXISTS` guards. Order doesn't matter
for genuinely additive changes — each migration must be safe to re-run.

Returns the list of migration names applied so the caller can log them. An
empty list means the DB was already up to date.
"""
from __future__ import annotations

import sqlite3


def apply_migrations(conn: sqlite3.Connection) -> list[str]:
    """Run every additive migration. Idempotent — safe on a fresh DB."""
    applied: list[str] = []

    # --- Tier 1, Upgrade 3: parsed salary columns on jobs ----------------
    if _add_column_if_missing(conn, "jobs", "comp_min", "REAL"):
        applied.append("jobs.comp_min")
    if _add_column_if_missing(conn, "jobs", "comp_max", "REAL"):
        applied.append("jobs.comp_max")
    if _add_column_if_missing(conn, "jobs", "comp_currency", "TEXT"):
        applied.append("jobs.comp_currency")
    if _add_column_if_missing(conn, "jobs", "comp_period", "TEXT"):
        applied.append("jobs.comp_period")

    # --- Tier 3, Upgrade 11: per-channel application pipeline ------------
    if _add_column_if_missing(
        conn, "applications", "channel", "TEXT NOT NULL DEFAULT 'ft'",
    ):
        applied.append("applications.channel")
        # Backfill from linked jobs. Runs once per migration apply.
        conn.execute(
            """
            UPDATE applications
               SET channel = COALESCE(
                   (SELECT j.channel FROM jobs j WHERE j.key = applications.job_key),
                   'ft'
               )
            """
        )
    # Idempotent index creation (re-runs are no-ops)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_applications_channel ON applications(channel)"
    )

    # --- Tier 3, Upgrade 8: stale-job detection on jobs ------------------
    if _add_column_if_missing(
        conn, "jobs", "is_closed", "INTEGER NOT NULL DEFAULT 0",
    ):
        applied.append("jobs.is_closed")
    if _add_column_if_missing(conn, "jobs", "closed_at", "TEXT"):
        applied.append("jobs.closed_at")
    if _add_column_if_missing(conn, "jobs", "last_rechecked_at", "TEXT"):
        applied.append("jobs.last_rechecked_at")
    if _add_column_if_missing(
        conn, "jobs", "recheck_attempts", "INTEGER NOT NULL DEFAULT 0",
    ):
        applied.append("jobs.recheck_attempts")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_is_closed ON jobs(is_closed)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_last_rechecked_at "
        "ON jobs(last_rechecked_at)"
    )

    # --- Trend-driven posts: link posts back to the trend they came from
    if _add_column_if_missing(conn, "posts", "trend_id", "INTEGER"):
        applied.append("posts.trend_id")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_posts_trend_id ON posts(trend_id)"
    )

    return applied


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, column_type: str,
) -> bool:
    """ALTER TABLE ADD COLUMN, guarded by introspection.

    Returns True if the column was added, False if it already existed.
    """
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    existing = {row[1] for row in rows}  # row[1] is the column name
    if column in existing:
        return False
    # ADD COLUMN doesn't support IF NOT EXISTS in SQLite — we just checked.
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
    return True
