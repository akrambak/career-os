from __future__ import annotations

import pytest

from career_os.db import Store
from career_os.models import Channel, JobPost
from career_os.tracker import (
    StageTransitionError,
    advance,
    funnel_counts,
    record_application,
)


def _store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'db.sqlite'}")


def _seed_job(store: Store, key_suffix: str = "1") -> str:
    job = JobPost(
        source="test", external_id=key_suffix,
        url="https://example.com/job/1",
        title="Senior Laravel + AI Engineer",
        description="x", channel=Channel.FT,
    )
    store.upsert_job(job)
    return job.key


def test_record_and_advance(tmp_path):
    store = _store(tmp_path)
    key = _seed_job(store)
    app = record_application(store, key)
    assert app.stage == "drafted"
    app = advance(store, key)
    assert app.stage == "sent"
    app = advance(store, key, to="interview")
    assert app.stage == "interview"


def test_record_unknown_job_raises(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(StageTransitionError):
        record_application(store, "nope:1")


def test_terminal_stages_block_advance(tmp_path):
    store = _store(tmp_path)
    key = _seed_job(store)
    record_application(store, key, stage="won")
    with pytest.raises(StageTransitionError):
        advance(store, key)


def test_funnel_counts_shape(tmp_path):
    store = _store(tmp_path)
    k1 = _seed_job(store, "a")
    k2 = _seed_job(store, "b")
    record_application(store, k1, stage="sent")
    record_application(store, k2, stage="interview")
    counts = funnel_counts(store)
    assert counts["sent"] == 1
    assert counts["interview"] == 1
    assert counts["drafted"] == 0
    assert sum(counts.values()) == 2
