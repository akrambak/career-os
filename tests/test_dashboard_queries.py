from __future__ import annotations

from datetime import UTC, datetime, timedelta

from career_os.dashboard.queries import (
    drafts_ready,
    funnel,
    source_health,
    top_matches,
    totals,
)
from career_os.db import Store
from career_os.models import Channel, JobPost, Score
from career_os.tracker import record_application


def _store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'db.sqlite'}")


def _seed_job(store: Store, key_suffix: str, fit: int | None = None,
              channel: Channel = Channel.FT, source: str = "test") -> str:
    job = JobPost(
        source=source, external_id=key_suffix,
        url=f"https://example.com/{key_suffix}",
        title=f"Job {key_suffix}", company="Acme",
        description="desc", channel=channel,
    )
    store.upsert_job(job)
    if fit is not None:
        store.save_score(Score(
            job_key=job.key, fit=fit, reasoning="x",
            pros=[], cons=[], suggested_angle="angle",
        ))
    return job.key


def test_totals_initially_zero(tmp_path):
    store = _store(tmp_path)
    assert totals(store) == {"jobs": 0, "scored": 0, "drafts": 0, "applications": 0}


def test_totals_counts_each_table(tmp_path):
    store = _store(tmp_path)
    k1 = _seed_job(store, "1", fit=72)
    _seed_job(store, "2")
    store.save_draft(k1, fmt="ft", body="hi", model="dry-run")
    record_application(store, k1)
    t = totals(store)
    assert t == {"jobs": 2, "scored": 1, "drafts": 1, "applications": 1}


def test_top_matches_filters_by_fit_and_channel(tmp_path):
    store = _store(tmp_path)
    _seed_job(store, "a", fit=80, channel=Channel.FT)
    _seed_job(store, "b", fit=50, channel=Channel.FT)
    _seed_job(store, "c", fit=85, channel=Channel.FREELANCE)
    out = top_matches(store, limit=10, min_fit=70, channel=None)
    keys = [r.job_key for r in out]
    assert len(keys) == 2
    assert all(r.fit >= 70 for r in out)
    only_freelance = top_matches(store, limit=10, min_fit=0, channel="freelance")
    assert len(only_freelance) == 1
    assert only_freelance[0].channel == "freelance"


def test_top_matches_flags_draft_and_stage(tmp_path):
    store = _store(tmp_path)
    k = _seed_job(store, "1", fit=80)
    store.save_draft(k, fmt="ft", body="hi", model="dry-run")
    record_application(store, k, stage="sent")
    out = top_matches(store, limit=5, min_fit=0)
    assert out[0].has_draft is True
    assert out[0].application_stage == "sent"


def test_drafts_ready_excludes_applied(tmp_path):
    store = _store(tmp_path)
    k1 = _seed_job(store, "1", fit=80)
    k2 = _seed_job(store, "2", fit=70)
    store.save_draft(k1, fmt="ft", body="hi", model="dry-run")
    store.save_draft(k2, fmt="ft", body="hi", model="dry-run")
    record_application(store, k2)
    out = drafts_ready(store, limit=10)
    assert len(out) == 1
    assert out[0].job_key == k1


def test_funnel_returns_all_stages(tmp_path):
    store = _store(tmp_path)
    k = _seed_job(store, "1", fit=80)
    record_application(store, k, stage="interview")
    f = funnel(store)
    assert f["interview"] == 1
    assert f["drafted"] == 0
    assert f["won"] == 0


def test_source_health_aggregates(tmp_path):
    store = _store(tmp_path)
    _seed_job(store, "a", source="remoteok")
    _seed_job(store, "b", source="remoteok")
    _seed_job(store, "c", source="remotive")
    sh = source_health(store)
    by_source = {s.source: s for s in sh}
    assert by_source["remoteok"].total == 2
    assert by_source["remotive"].total == 1
    # Just-inserted jobs should show up in the 24h window
    assert by_source["remoteok"].last_24h == 2


def test_source_health_24h_cutoff(tmp_path):
    """Old jobs shouldn't count toward last_24h."""
    store = _store(tmp_path)
    # Insert a job, then manually backdate its fetched_at.
    _seed_job(store, "old", source="remoteok")
    long_ago = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    with store._conn() as c:
        c.execute("UPDATE jobs SET fetched_at = ? WHERE source = 'remoteok'", (long_ago,))
    sh = source_health(store)
    by_source = {s.source: s for s in sh}
    assert by_source["remoteok"].last_24h == 0
    assert by_source["remoteok"].last_7d == 0
    assert by_source["remoteok"].total == 1
