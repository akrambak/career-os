from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from career_os.db import Store
from career_os.models import Channel, JobPost
from career_os.tracker import record_application, stale_applications


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'nudges.db'}")


def _job(store, key, channel=Channel.FT):
    job = JobPost(
        source="test", external_id=key, url=f"https://e.com/{key}",
        title=f"Job {key}", description="d", channel=channel,
    )
    store.upsert_job(job)
    return job.key


def _age(store, job_key, days):
    ts = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with store._conn() as c:
        c.execute(
            "UPDATE applications SET updated_at = ? WHERE job_key = ?",
            (ts, job_key),
        )


def test_only_stale_non_terminal_apps_returned(store):
    stale = _job(store, "stale")
    fresh = _job(store, "fresh")
    record_application(store, stale, stage="sent")
    record_application(store, fresh, stage="sent")
    _age(store, stale, 10)
    _age(store, fresh, 2)

    nudges = stale_applications(store, days=7)
    assert [n.app.job_key for n in nudges] == [stale]
    assert nudges[0].days_stale == 10


def test_terminal_stages_never_stale(store):
    won = _job(store, "won")
    record_application(store, won, stage="won")
    _age(store, won, 30)
    assert stale_applications(store, days=7) == []


def test_sorted_most_stale_first(store):
    a = _job(store, "a")
    b = _job(store, "b")
    record_application(store, a, stage="sent")
    record_application(store, b, stage="sent")
    _age(store, a, 8)
    _age(store, b, 20)

    nudges = stale_applications(store, days=7)
    assert [n.app.job_key for n in nudges] == [b, a]


def test_suggestion_is_stage_specific(store):
    drafted = _job(store, "drafted")
    sent = _job(store, "sent")
    record_application(store, drafted, stage="drafted")
    record_application(store, sent, stage="sent")
    _age(store, drafted, 10)
    _age(store, sent, 10)

    by_key = {n.app.job_key: n for n in stale_applications(store, days=7)}
    assert "never sent" in by_key[drafted].suggestion
    assert "follow-up" in by_key[sent].suggestion.lower()


def test_days_threshold_boundary_is_strict(store):
    k = _job(store, "edge")
    record_application(store, k, stage="sent")
    fixed = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    with store._conn() as c:
        c.execute(
            "UPDATE applications SET updated_at = ? WHERE job_key = ?",
            ((fixed - timedelta(days=7)).isoformat(), k),
        )
    # Exactly 7d old at the cutoff is not yet stale (strict <); one second more is.
    assert stale_applications(store, days=7, now=fixed) == []
    assert len(stale_applications(store, days=7, now=fixed + timedelta(seconds=1))) == 1


def test_fixed_now_makes_staleness_deterministic(store):
    k = _job(store, "k")
    record_application(store, k, stage="sent")
    _age(store, k, 9)
    now = datetime.now(UTC) + timedelta(hours=1)
    nudges = stale_applications(store, days=7, now=now)
    assert nudges[0].days_stale == 9
