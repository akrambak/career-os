from __future__ import annotations

from career_os.db import Store
from career_os.models import Channel, JobPost, Score


def _job(key_suffix: str = "1") -> JobPost:
    return JobPost(
        source="test",
        external_id=key_suffix,
        url="https://example.com/job/1",
        title="Senior Laravel + AI Engineer",
        company="ExampleCo",
        description="Build agents on top of a Laravel monolith.",
        tags=["laravel", "ai"],
        channel=Channel.FT,
    )


def test_upsert_returns_true_then_false(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'db.sqlite'}")
    j = _job()
    assert store.upsert_job(j) is True
    assert store.upsert_job(j) is False


def test_unscored_then_scored(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'db.sqlite'}")
    j = _job()
    store.upsert_job(j)
    assert [u.key for u in store.unscored_jobs()] == [j.key]
    store.save_score(Score(
        job_key=j.key, fit=72, reasoning="solid match",
        pros=["laravel"], cons=[],
    ))
    assert store.unscored_jobs() == []
    top = store.top_scored(limit=5, min_fit=70)
    assert len(top) == 1
    assert top[0][1].fit == 72


def test_freelance_channel_round_trip(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'db.sqlite'}")
    j = _job("2")
    j_freelance = j.model_copy(update={"external_id": "2", "channel": Channel.FREELANCE})
    store.upsert_job(j_freelance)
    out = store.unscored_jobs()
    assert out[0].channel == Channel.FREELANCE
