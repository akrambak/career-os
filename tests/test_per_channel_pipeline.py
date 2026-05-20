"""Tier 3 Upgrade 11 — per-channel pipeline tests.

Coverage:
  - Freelance applications walk scope_call → proposal_sent → signed_proposal
  - FT applications walk replied → interview → offer
  - Cross-channel transitions are rejected
  - Terminal stages (won/rejected/dropped) are shared
  - EITHER jobs default to FT pipeline
  - record_application populates application.channel from job.channel
  - funnel_counts returns nested per-channel shape
  - Migration backfills channel on a legacy applications row (no channel col)
"""
from __future__ import annotations

import sqlite3

import pytest

from career_os.db import Store
from career_os.db.migrations import apply_migrations
from career_os.models import Channel, JobPost
from career_os.tracker import (
    ALL_STAGES,
    FREELANCE_STAGES,
    FT_STAGES,
    StageTransitionError,
    advance,
    funnel_counts,
    record_application,
    stages_for_channel,
)


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'pl.db'}")


def _seed(store: Store, key: str, channel: Channel) -> str:
    job = JobPost(
        source="test", external_id=key,
        url=f"https://example.com/{key}",
        title=f"Job {key}", description="d", channel=channel,
    )
    store.upsert_job(job)
    return job.key


# ---- happy path -----------------------------------------------------------

def test_freelance_walks_scope_call_chain(store):
    k = _seed(store, "1", Channel.FREELANCE)
    record_application(store, k)
    assert advance(store, k).stage == "sent"
    assert advance(store, k).stage == "scope_call"
    assert advance(store, k).stage == "proposal_sent"
    assert advance(store, k).stage == "signed_proposal"
    # next step lands in shared terminals via explicit --to
    assert advance(store, k, to="won").stage == "won"


def test_ft_walks_interview_chain(store):
    k = _seed(store, "1", Channel.FT)
    record_application(store, k)
    assert advance(store, k).stage == "sent"
    assert advance(store, k).stage == "replied"
    assert advance(store, k).stage == "interview"
    assert advance(store, k).stage == "offer"


def test_either_channel_uses_ft_pipeline(store):
    k = _seed(store, "1", Channel.EITHER)
    record_application(store, k)
    # Either should walk the FT chain.
    assert advance(store, k).stage == "sent"
    assert advance(store, k).stage == "replied"


# ---- cross-channel transitions are rejected -------------------------------

def test_freelance_rejects_ft_only_stage(store):
    k = _seed(store, "1", Channel.FREELANCE)
    record_application(store, k)
    with pytest.raises(StageTransitionError) as ei:
        advance(store, k, to="interview")
    assert "freelance" in str(ei.value)


def test_ft_rejects_freelance_only_stage(store):
    k = _seed(store, "1", Channel.FT)
    record_application(store, k)
    with pytest.raises(StageTransitionError) as ei:
        advance(store, k, to="scope_call")
    assert "ft" in str(ei.value)


def test_record_application_rejects_wrong_channel_stage(store):
    k = _seed(store, "1", Channel.FT)
    with pytest.raises(StageTransitionError):
        record_application(store, k, stage="scope_call")


# ---- terminals are shared -------------------------------------------------

def test_terminals_legal_for_freelance(store):
    k = _seed(store, "1", Channel.FREELANCE)
    record_application(store, k, stage="won")
    # Already at terminal — no further advance.
    with pytest.raises(StageTransitionError):
        advance(store, k)


def test_terminals_legal_for_ft(store):
    k = _seed(store, "1", Channel.FT)
    record_application(store, k, stage="rejected")
    with pytest.raises(StageTransitionError):
        advance(store, k)


# ---- channel column populated from job -----------------------------------

def test_application_channel_matches_job_channel(store):
    ft_key = _seed(store, "ft1", Channel.FT)
    fl_key = _seed(store, "fl1", Channel.FREELANCE)
    ft_app = record_application(store, ft_key)
    fl_app = record_application(store, fl_key)
    assert ft_app.channel == "ft"
    assert fl_app.channel == "freelance"


# ---- nested funnel shape -------------------------------------------------

def test_funnel_separates_channels(store):
    fl1 = _seed(store, "fl1", Channel.FREELANCE)
    fl2 = _seed(store, "fl2", Channel.FREELANCE)
    ft1 = _seed(store, "ft1", Channel.FT)
    record_application(store, fl1, stage="scope_call")
    record_application(store, fl2, stage="proposal_sent")
    record_application(store, ft1, stage="interview")

    counts = funnel_counts(store)
    assert counts["freelance"]["scope_call"] == 1
    assert counts["freelance"]["proposal_sent"] == 1
    # interview isn't part of the freelance pipeline — not even a 0 entry.
    assert "interview" not in counts["freelance"]
    assert counts["ft"]["interview"] == 1
    assert "scope_call" not in counts["ft"]


def test_funnel_seeds_every_stage_to_zero(store):
    counts = funnel_counts(store)
    for stage in FT_STAGES:
        assert counts["ft"][stage] == 0
    for stage in FREELANCE_STAGES:
        assert counts["freelance"][stage] == 0


# ---- helpers --------------------------------------------------------------

def test_stages_for_channel_includes_terminals():
    ft = stages_for_channel("ft")
    assert ft[: len(FT_STAGES)] == FT_STAGES
    assert ft[-3:] == ("won", "rejected", "dropped")


def test_all_stages_is_dedup_union():
    # 'drafted', 'sent', terminals appear in both — should only show once.
    assert ALL_STAGES.count("drafted") == 1
    assert ALL_STAGES.count("sent") == 1
    assert ALL_STAGES.count("won") == 1


# ---- migration backfill ---------------------------------------------------

def test_migration_backfills_channel_from_linked_job(tmp_path):
    """Simulate a pre-Tier-3 DB: applications table with no `channel`
    column. After Store init runs migrations, existing rows should be
    backfilled from their joined job's channel."""
    db_path = tmp_path / "legacy.db"
    raw = sqlite3.connect(db_path)
    raw.executescript("""
        CREATE TABLE jobs (
            key TEXT PRIMARY KEY, source TEXT, external_id TEXT, url TEXT,
            title TEXT, company TEXT, location TEXT, description TEXT,
            tags TEXT, channel TEXT, compensation TEXT, posted_at TEXT,
            fetched_at TEXT
        );
        CREATE TABLE applications (
            job_key TEXT PRIMARY KEY, stage TEXT, notes TEXT,
            applied_at TEXT, updated_at TEXT
        );
        INSERT INTO jobs (key, source, external_id, url, title, description, tags,
                          channel, fetched_at)
        VALUES ('test:1','test','1','https://e.com/1','t','d','[]','freelance','2026-05-19');
        INSERT INTO jobs (key, source, external_id, url, title, description, tags,
                          channel, fetched_at)
        VALUES ('test:2','test','2','https://e.com/2','t','d','[]','ft','2026-05-19');
        INSERT INTO applications (job_key, stage, notes, applied_at, updated_at)
        VALUES ('test:1','sent',NULL,'2026-05-19','2026-05-19');
        INSERT INTO applications (job_key, stage, notes, applied_at, updated_at)
        VALUES ('test:2','interview',NULL,'2026-05-19','2026-05-19');
    """)
    raw.commit()
    raw.close()

    # Open via Store — triggers migrations.
    store = Store(f"sqlite:///{db_path}")

    # Backfilled column values should match each application's linked job.
    with store._conn() as c:  # noqa: SLF001
        rows = {
            r["job_key"]: r["channel"]
            for r in c.execute(
                "SELECT job_key, channel FROM applications"
            ).fetchall()
        }
    assert rows["test:1"] == "freelance"
    assert rows["test:2"] == "ft"


def test_migration_is_idempotent(tmp_path):
    """Running migrations twice on an already-migrated DB is a no-op."""
    store = Store(f"sqlite:///{tmp_path / 'fresh.db'}")
    with store._conn() as c:  # noqa: SLF001
        applied_a = apply_migrations(c)
        applied_b = apply_migrations(c)
    # Both calls should return empty applied lists (every migration was already
    # applied during _init_schema and the second apply_migrations).
    assert applied_a == []
    assert applied_b == []
