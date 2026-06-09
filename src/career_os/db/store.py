from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path

from ..models import Channel, JobPost, Score
from .migrations import apply_migrations


def _logger() -> logging.Logger:
    return logging.getLogger(__name__)

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

-- Content pipeline: Ideas and Posts are intentionally independent (no
-- promote-flow). Ideas = raw seed jottings. Posts = drafts being shaped
-- toward publish. Each page owns its own table.
CREATE TABLE IF NOT EXISTS ideas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    hook          TEXT,
    channel       TEXT NOT NULL DEFAULT 'blog',
    tags          TEXT NOT NULL DEFAULT '[]',
    notes         TEXT,
    archived      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ideas_channel ON ideas(channel);
CREATE INDEX IF NOT EXISTS idx_ideas_archived ON ideas(archived);

CREATE TABLE IF NOT EXISTS posts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL,
    channel       TEXT NOT NULL DEFAULT 'blog',
    status        TEXT NOT NULL DEFAULT 'drafting',
    body          TEXT NOT NULL DEFAULT '',
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    posted_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel);

-- Backlinks inventory (SEO Feature 1). One row per (source_url,
-- target_url) — the source page linking TO us. Status reflects
-- whether the link is still live; weekly recheck (career-os
-- backlinks-recheck) walks each row.
CREATE TABLE IF NOT EXISTS backlinks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url        TEXT NOT NULL,
    source_domain     TEXT NOT NULL,
    target_url        TEXT NOT NULL,
    anchor_text       TEXT,
    rel               TEXT NOT NULL DEFAULT 'dofollow',
                                                 -- dofollow|nofollow|ugc|sponsored
    status            TEXT NOT NULL DEFAULT 'live',
                                                 -- live|dead|redirect|removed|unverified
    da_estimate       INTEGER,
    discovered_via    TEXT NOT NULL DEFAULT 'manual',
                                                 -- manual|mention_hunter|gsc|gh_search
    first_seen_at     TEXT NOT NULL,
    last_checked_at   TEXT,
    recheck_attempts  INTEGER NOT NULL DEFAULT 0,
    notes             TEXT,
    UNIQUE(source_url, target_url)
);
CREATE INDEX IF NOT EXISTS idx_backlinks_source_domain ON backlinks(source_domain);
CREATE INDEX IF NOT EXISTS idx_backlinks_status ON backlinks(status);
CREATE INDEX IF NOT EXISTS idx_backlinks_rel ON backlinks(rel);
CREATE INDEX IF NOT EXISTS idx_backlinks_last_checked ON backlinks(last_checked_at);

-- Outreach targets (SEO Feature 2). State machine per target:
-- researching → pitched → replied → accepted → published OR declined/dropped.
-- One row per (site_url, category) so the same site can be hit for both
-- a guest post and a directory listing.
CREATE TABLE IF NOT EXISTS outreach_targets (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    site_url            TEXT NOT NULL,
    site_domain         TEXT NOT NULL,
    category            TEXT NOT NULL,
                                       -- podcast|guest_post|directory|haro|
                                       -- roundup|community|newsletter|unlinked_mention
    contact             TEXT,
    pitch_angle         TEXT,
    stage               TEXT NOT NULL DEFAULT 'researching',
                                       -- researching|pitched|replied|accepted|
                                       -- published|declined|dropped
    value_score         INTEGER NOT NULL DEFAULT 5,    -- 1-10
    da_estimate         INTEGER,
    target_backlink_url TEXT,
    pitch_draft         TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    pitched_at          TEXT,
    published_at        TEXT,
    UNIQUE(site_url, category)
);
CREATE INDEX IF NOT EXISTS idx_outreach_targets_stage ON outreach_targets(stage);
CREATE INDEX IF NOT EXISTS idx_outreach_targets_category ON outreach_targets(category);
CREATE INDEX IF NOT EXISTS idx_outreach_targets_updated ON outreach_targets(updated_at);

-- Mention Hunter (SEO Feature 3). Auto-discovered references to the
-- user's domain / repo / handles across HN / dev.to / GitHub.
-- has_link=0 = unlinked → convert via outreach. has_link=1 = already
-- linked → cross-check vs backlinks (likely upserted there too).
CREATE TABLE IF NOT EXISTS mentions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,            -- hn|devto|github|reddit|tavily|manual
    source_url      TEXT NOT NULL,
    matched_term    TEXT NOT NULL,
    context_snippet TEXT,
    has_link        INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'open',
                                              -- open|converted|dismissed|linked
    discovered_at   TEXT NOT NULL,
    notes           TEXT,
    UNIQUE(source_url, matched_term)
);
CREATE INDEX IF NOT EXISTS idx_mentions_status ON mentions(status);
CREATE INDEX IF NOT EXISTS idx_mentions_has_link ON mentions(has_link);
CREATE INDEX IF NOT EXISTS idx_mentions_source ON mentions(source);

-- Trend feed (trend-driven post generator). Scraped from HN, dev.to,
-- Tavily; ranked by signal_score (base × recency × topic-fit).
-- UNIQUE(source, external_id) dedups across re-scans — upserts refresh
-- score/comment_count and recompute signal_score in-place.
CREATE TABLE IF NOT EXISTS trends (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,                  -- hn | devto | reddit | tavily | manual
    external_id   TEXT,
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT,
    score         INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    tags          TEXT NOT NULL DEFAULT '[]',
    raw           TEXT NOT NULL DEFAULT '{}',
    signal_score  REAL NOT NULL DEFAULT 0,
    fetched_at    TEXT NOT NULL,
    used_at       TEXT,
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_trends_signal ON trends(signal_score DESC);
CREATE INDEX IF NOT EXISTS idx_trends_source ON trends(source);
CREATE INDEX IF NOT EXISTS idx_trends_fetched ON trends(fetched_at);

-- Per-week KPI snapshots (Pillar 3). Auto-derived KPIs are computed from
-- the other tables; manually-tracked KPIs (LinkedIn impressions, etc.)
-- are entered via the dashboard form. `week_start` is always a Monday
-- ISO date so weekly aggregation is unambiguous.
CREATE TABLE IF NOT EXISTS kpi_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start    TEXT NOT NULL,           -- YYYY-MM-DD (Monday)
    kpi_key       TEXT NOT NULL,
    value         REAL NOT NULL,
    target        REAL,
    source        TEXT NOT NULL DEFAULT 'manual',  -- manual | derived
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(week_start, kpi_key)
);
CREATE INDEX IF NOT EXISTS idx_kpi_snapshots_key ON kpi_snapshots(kpi_key);
CREATE INDEX IF NOT EXISTS idx_kpi_snapshots_week ON kpi_snapshots(week_start);

-- Automations: cron-style schedules the user has armed. The runtime
-- (CLI / dashboard "Run now" button) walks rows where is_armed=1 AND
-- next_run_due_at <= NOW, executes the named job, records to
-- automation_runs, and updates next_run_due_at.
CREATE TABLE IF NOT EXISTS automations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,           -- 'fetch_hourly', etc.
    kind                TEXT NOT NULL,                  -- maps to a registered handler
    interval_minutes    INTEGER NOT NULL,
    config              TEXT NOT NULL DEFAULT '{}',     -- JSON: per-kind options
    is_armed            INTEGER NOT NULL DEFAULT 1,
    last_run_at         TEXT,
    next_run_due_at     TEXT,
    last_status         TEXT,                           -- ok | failed | skipped
    last_summary        TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automations_armed_due
    ON automations(is_armed, next_run_due_at);

CREATE TABLE IF NOT EXISTS automation_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    automation_id INTEGER NOT NULL REFERENCES automations(id) ON DELETE CASCADE,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL,                        -- ok | failed | skipped
    summary       TEXT,
    error_detail  TEXT
);
CREATE INDEX IF NOT EXISTS idx_automation_runs_automation
    ON automation_runs(automation_id);

-- HITL action inbox: every automation that wants the user's attention
-- creates a row here. UNIQUE(kind, target_kind, target_id) makes
-- generators idempotent — re-running them never duplicates an open action.
CREATE TABLE IF NOT EXISTS actions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    severity      TEXT NOT NULL DEFAULT 'normal',  -- urgent | normal | low
    target_kind   TEXT,
    target_id     TEXT,
    payload       TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'open',  -- open|approved|dismissed|deferred|snoozed
    snoozed_until TEXT,
    resolved_at   TEXT,
    resolved_note TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(kind, target_kind, target_id)
);
CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
CREATE INDEX IF NOT EXISTS idx_actions_severity ON actions(severity);
CREATE INDEX IF NOT EXISTS idx_actions_kind ON actions(kind);
CREATE INDEX IF NOT EXISTS idx_actions_snoozed_until ON actions(snoozed_until);

-- Per-source incremental-fetch watermarks (Tier 2, Upgrade 6).
-- One row per logical sub-feed: e.g. WeWorkRemotely has two RSS feeds, each
-- recorded under a composite key like 'weworkremotely:programming'.
-- A top-level row for each scraper.key tracks overall run status.
CREATE TABLE IF NOT EXISTS source_watermarks (
    source           TEXT PRIMARY KEY,
    last_fetched_at  TEXT NOT NULL,
    last_status      TEXT NOT NULL,          -- ok | unchanged | partial | failed
    etag             TEXT,
    last_modified    TEXT,
    last_external_id TEXT,
    last_cursor      TEXT,
    notes            TEXT
);
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
            # WAL is persistent in the DB header — set once here and every
            # later connection inherits it without re-issuing the pragma.
            c.execute("PRAGMA journal_mode = WAL")
            c.executescript(SCHEMA)
            apply_migrations(c)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        # WAL (set once in _init_schema) lets the dashboard read while the
        # automations runner / CLI write. These three are per-connection
        # state and must be re-set on every connection: busy_timeout makes
        # concurrent writers wait-and-retry instead of failing fast with
        # "database is locked".
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_job(self, job: JobPost) -> bool:
        """Insert or update one job; True if it was newly inserted."""
        return self.upsert_jobs((job,)) == 1

    def upsert_jobs(self, jobs: Iterable[JobPost]) -> int:
        """Batch upsert in a single connection/transaction. Returns the count
        of rows newly inserted (updates don't count). One commit per call —
        a multi-source crawl no longer pays a connect+commit per job.
        """
        new = 0
        with self._conn() as c:
            for job in jobs:
                comp = job.parsed_compensation
                exists = c.execute(
                    "SELECT 1 FROM jobs WHERE key = ?", (job.key,)
                ).fetchone() is not None
                c.execute(
                    """
                    INSERT INTO jobs (key, source, external_id, url, title, company,
                                      location, description, tags, channel,
                                      compensation, posted_at, fetched_at,
                                      comp_min, comp_max, comp_currency, comp_period)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        title=excluded.title,
                        company=excluded.company,
                        location=excluded.location,
                        description=excluded.description,
                        tags=excluded.tags,
                        channel=excluded.channel,
                        compensation=excluded.compensation,
                        fetched_at=excluded.fetched_at,
                        comp_min=excluded.comp_min,
                        comp_max=excluded.comp_max,
                        comp_currency=excluded.comp_currency,
                        comp_period=excluded.comp_period,
                        -- If we see a previously-closed job again, the source
                        -- re-listed it — reset closure state.
                        is_closed=0,
                        closed_at=NULL,
                        last_rechecked_at=NULL,
                        recheck_attempts=0
                    """,
                    (
                        job.key, job.source, job.external_id, str(job.url),
                        job.title, job.company, job.location, job.description,
                        json.dumps(job.tags), job.channel.value, job.compensation,
                        job.posted_at.isoformat() if job.posted_at else None,
                        job.fetched_at.isoformat(),
                        comp.min_amount if comp else None,
                        comp.max_amount if comp else None,
                        comp.currency if comp else None,
                        comp.period if comp else None,
                    ),
                )
                if not exists:
                    new += 1
        return new

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

    # ---- stale-job detection (Tier 3, Upgrade 8) -------------------------

    def recheck_candidates(
        self, limit: int = 200, max_age_days: int = 7,
        source: str | None = None,
    ) -> list[JobPost]:
        """Jobs that are still flagged active but haven't been rechecked in
        `max_age_days` days. Returns rows where `last_rechecked_at` is NULL
        (never checked) or older than the cutoff. Caller decides what to do
        with each — this method only selects."""
        from datetime import datetime, timedelta
        cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()
        sql = (
            "SELECT * FROM jobs WHERE is_closed = 0 "
            "AND (last_rechecked_at IS NULL OR last_rechecked_at < ?)"
        )
        params: list = [cutoff]
        if source:
            sql += " AND source = ?"
            params.append(source)
        sql += (
            " ORDER BY COALESCE(last_rechecked_at, '0000-00-00') ASC, fetched_at ASC "
            "LIMIT ?"
        )
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, tuple(params)).fetchall()
        return [_row_to_job(r) for r in rows]

    def mark_closed(self, key: str, reason: str) -> None:
        """Set is_closed=1, record closed_at + last_rechecked_at + reason."""
        from datetime import datetime
        now = datetime.now(UTC).isoformat()
        with self._conn() as c:
            c.execute(
                "UPDATE jobs SET is_closed=1, closed_at=?, last_rechecked_at=? "
                "WHERE key=?",
                (now, now, key),
            )
            # Reason goes into source_watermarks notes? No — store on job
            # via a tiny side channel. The simplest place is a comment in
            # `description` would be lossy. For now, log via stdlib logger;
            # tier 3 doesn't promise a per-job reason history field.
            c.execute(
                "UPDATE jobs SET tags = tags || '' WHERE key = ?", (key,),
            )  # noop touch to commit
        _logger().info("marked closed: %s reason=%s", key, reason)

    def mark_recheck_attempt(self, key: str, *, transient: bool) -> int:
        """Bump recheck_attempts + update last_rechecked_at. Returns the
        new attempts count. `transient=True` means the failure was transient
        (5xx, timeout) — caller can decide on 3-strikes-and-close based on
        the return value."""
        from datetime import datetime
        now = datetime.now(UTC).isoformat()
        with self._conn() as c:
            if transient:
                c.execute(
                    "UPDATE jobs SET recheck_attempts = recheck_attempts + 1, "
                    "last_rechecked_at=? WHERE key=?",
                    (now, key),
                )
            else:
                # Successful recheck: clear attempts, mark fresh.
                c.execute(
                    "UPDATE jobs SET recheck_attempts = 0, last_rechecked_at=? "
                    "WHERE key=?",
                    (now, key),
                )
            row = c.execute(
                "SELECT recheck_attempts FROM jobs WHERE key=?", (key,),
            ).fetchone()
        return int(row["recheck_attempts"]) if row else 0

    def closed_count_since(self, cutoff_iso: str) -> dict[str, int]:
        """Per-source count of jobs marked closed since `cutoff_iso`."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT source, COUNT(*) AS n FROM jobs "
                "WHERE is_closed=1 AND closed_at >= ? GROUP BY source",
                (cutoff_iso,),
            ).fetchall()
        return {r["source"]: int(r["n"]) for r in rows}

    # ---- watermarks (Tier 2, Upgrade 6) ----------------------------------

    def get_watermark(self, source: str):
        """Return the current Watermark for a source key, or None."""
        from ..watermark import Watermark
        with self._conn() as c:
            row = c.execute(
                "SELECT source, last_fetched_at, last_status, etag, "
                "last_modified, last_external_id, last_cursor, notes "
                "FROM source_watermarks WHERE source = ?",
                (source,),
            ).fetchone()
        if not row:
            return None
        from datetime import datetime
        return Watermark(
            source=row["source"],
            last_fetched_at=datetime.fromisoformat(row["last_fetched_at"]),
            last_status=row["last_status"],
            etag=row["etag"],
            last_modified=row["last_modified"],
            last_external_id=row["last_external_id"],
            last_cursor=row["last_cursor"],
            notes=row["notes"],
        )

    def save_watermark(
        self, *, source: str, last_fetched_at: str, last_status: str,
        etag: str | None = None, last_modified: str | None = None,
        last_external_id: str | None = None, last_cursor: str | None = None,
        notes: str | None = None,
    ) -> None:
        """Upsert one watermark row. Caller-supplied `last_fetched_at` is
        ISO-8601; this is friendlier than always computing UTC inside the
        store because the crawler likes to share a single timestamp across
        multiple sub-feed writes from the same run.
        """
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO source_watermarks
                    (source, last_fetched_at, last_status, etag, last_modified,
                     last_external_id, last_cursor, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_fetched_at=excluded.last_fetched_at,
                    last_status=excluded.last_status,
                    etag=COALESCE(excluded.etag, source_watermarks.etag),
                    last_modified=COALESCE(
                        excluded.last_modified, source_watermarks.last_modified
                    ),
                    last_external_id=COALESCE(
                        excluded.last_external_id, source_watermarks.last_external_id
                    ),
                    last_cursor=COALESCE(
                        excluded.last_cursor, source_watermarks.last_cursor
                    ),
                    notes=COALESCE(excluded.notes, source_watermarks.notes)
                """,
                (
                    source, last_fetched_at, last_status, etag, last_modified,
                    last_external_id, last_cursor, notes,
                ),
            )

    def list_watermarks(self) -> list:
        """Return all watermark rows — used by the dashboard source-health
        join."""
        from datetime import datetime

        from ..watermark import Watermark
        with self._conn() as c:
            rows = c.execute(
                "SELECT source, last_fetched_at, last_status, etag, "
                "last_modified, last_external_id, last_cursor, notes "
                "FROM source_watermarks"
            ).fetchall()
        return [
            Watermark(
                source=r["source"],
                last_fetched_at=datetime.fromisoformat(r["last_fetched_at"]),
                last_status=r["last_status"],
                etag=r["etag"],
                last_modified=r["last_modified"],
                last_external_id=r["last_external_id"],
                last_cursor=r["last_cursor"],
                notes=r["notes"],
            ) for r in rows
        ]

    def top_scored(self, limit: int = 5, min_fit: int = 0) -> list[tuple[JobPost, Score]]:
        with self._conn() as c:
            rows = c.execute(
                """
                SELECT j.*, s.fit, s.reasoning, s.pros, s.cons,
                       s.suggested_angle, s.scored_at
                FROM jobs j JOIN scores s ON s.job_key = j.key
                WHERE s.fit >= ? AND j.is_closed = 0
                ORDER BY s.fit DESC, j.fetched_at DESC
                LIMIT ?
                """,
                (min_fit, limit),
            ).fetchall()
        return [(_row_to_job(r), _row_to_score(r)) for r in rows]


def _row_to_job(row: sqlite3.Row) -> JobPost:
    from datetime import datetime

    from ..salary import Compensation
    # The parsed-comp columns are added by a migration; on a freshly-migrated
    # DB they exist but may be NULL on rows ingested before the migration ran.
    # Use dict-access with .get to stay backward-compatible with any caller
    # that constructs Row objects without those columns (e.g., a partial
    # SELECT in a test).
    row_dict = dict(row)
    comp_min = row_dict.get("comp_min")
    comp_max = row_dict.get("comp_max")
    comp_currency = row_dict.get("comp_currency")
    comp_period = row_dict.get("comp_period")
    parsed_comp: Compensation | None = None
    if comp_min is not None or comp_max is not None:
        parsed_comp = Compensation(
            min_amount=float(comp_min) if comp_min is not None else None,
            max_amount=float(comp_max) if comp_max is not None else None,
            currency=comp_currency,
            period=comp_period,
            raw=row["compensation"] or "",
        )
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
        parsed_compensation=parsed_comp,
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
