"""HITL Inbox — actions module tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from career_os import actions as actions_lib
from career_os.db import Store
from career_os.models import Channel, JobPost, Score


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'actions.db'}")


def _job(store, key="1", channel=Channel.FT, fit: int | None = None,
         with_draft: bool = False, closed: bool = False):
    job = JobPost(
        source="test", external_id=key, url=f"https://e.com/{key}",
        title=f"Senior Eng {key}", company="Acme", description="d",
        channel=channel,
    )
    store.upsert_job(job)
    if fit is not None:
        store.save_score(Score(
            job_key=job.key, fit=fit, reasoning="x", pros=[], cons=[],
            suggested_angle="angle",
        ))
    if with_draft:
        store.save_draft(job.key, fmt="ft", body="hi", model="test")
    if closed:
        store.mark_closed(job.key, reason="gone")
    return job.key


# ---- CRUD ----------------------------------------------------------------

def test_upsert_action_creates_new(store):
    a = actions_lib.upsert_action(
        store, kind="generic", title="hello",
        target_kind="job", target_id="test:1",
    )
    assert a.id > 0
    assert a.status == "open"
    assert a.severity == "normal"
    assert a.title == "hello"


def test_upsert_action_idempotent_on_same_target(store):
    a = actions_lib.upsert_action(
        store, kind="review_job", title="first",
        target_kind="job", target_id="test:1",
    )
    b = actions_lib.upsert_action(
        store, kind="review_job", title="updated title",
        target_kind="job", target_id="test:1",
    )
    assert a.id == b.id  # same row, updated in place
    assert b.title == "updated title"
    open_rows = actions_lib.list_actions(store)
    assert len(open_rows) == 1


def test_upsert_does_not_reopen_resolved(store):
    a = actions_lib.upsert_action(
        store, kind="review_job", title="x",
        target_kind="job", target_id="test:1",
    )
    actions_lib.resolve(store, a.id, "dismissed")
    # Try to re-create the same (kind, target) — should NOT re-open.
    b = actions_lib.upsert_action(
        store, kind="review_job", title="y",
        target_kind="job", target_id="test:1",
    )
    assert b.status == "dismissed"
    assert actions_lib.list_actions(store) == []


def test_invalid_severity_raises(store):
    with pytest.raises(ValueError):
        actions_lib.upsert_action(store, kind="x", title="t", severity="emergency")


# ---- resolve + snooze ----------------------------------------------------

def test_resolve_approve(store):
    a = actions_lib.upsert_action(store, kind="x", title="t")
    resolved = actions_lib.resolve(store, a.id, "approved", note="did it")
    assert resolved.status == "approved"
    assert resolved.resolved_note == "did it"
    assert resolved.resolved_at is not None


def test_resolve_unknown_status_raises(store):
    a = actions_lib.upsert_action(store, kind="x", title="t")
    with pytest.raises(ValueError):
        actions_lib.resolve(store, a.id, "snoozed")  # not a resolve target


def test_snooze_hides_from_open_list(store):
    a = actions_lib.upsert_action(store, kind="x", title="t")
    future = datetime.now(UTC) + timedelta(hours=24)
    actions_lib.snooze(store, a.id, future)
    open_rows = actions_lib.list_actions(store)
    assert open_rows == []


def test_snooze_past_resurfaces(store):
    a = actions_lib.upsert_action(store, kind="x", title="t")
    past = datetime.now(UTC) - timedelta(minutes=5)
    actions_lib.snooze(store, a.id, past)
    open_rows = actions_lib.list_actions(store)
    assert len(open_rows) == 1


# ---- counts + filters ----------------------------------------------------

def test_counts_by_severity(store):
    actions_lib.upsert_action(store, kind="x", title="a", severity="urgent",
                              target_kind="t", target_id="1")
    actions_lib.upsert_action(store, kind="x", title="b", severity="urgent",
                              target_kind="t", target_id="2")
    actions_lib.upsert_action(store, kind="x", title="c", severity="normal",
                              target_kind="t", target_id="3")
    counts = actions_lib.counts_by_severity(store)
    assert counts["urgent"] == 2
    assert counts["normal"] == 1
    assert counts["low"] == 0


def test_list_filters_by_kind_and_severity(store):
    actions_lib.upsert_action(store, kind="review_job", title="a",
                              severity="urgent", target_kind="t", target_id="1")
    actions_lib.upsert_action(store, kind="send_draft", title="b",
                              severity="normal", target_kind="t", target_id="2")
    just_review = actions_lib.list_actions(store, kind="review_job")
    just_urgent = actions_lib.list_actions(store, severity="urgent")
    assert [a.kind for a in just_review] == ["review_job"]
    assert [a.severity for a in just_urgent] == ["urgent"]


def test_list_sorts_urgent_first(store):
    actions_lib.upsert_action(store, kind="x", title="low", severity="low",
                              target_kind="t", target_id="1")
    actions_lib.upsert_action(store, kind="x", title="urgent", severity="urgent",
                              target_kind="t", target_id="2")
    actions_lib.upsert_action(store, kind="x", title="normal", severity="normal",
                              target_kind="t", target_id="3")
    rows = actions_lib.list_actions(store)
    assert [a.severity for a in rows] == ["urgent", "normal", "low"]


# ---- generators (idempotent) ---------------------------------------------

def test_gen_review_high_fit_jobs(store):
    _job(store, "1", fit=85)             # urgent
    _job(store, "2", fit=78)             # normal (≥75 threshold, <85)
    _job(store, "3", fit=40)             # below threshold, skipped
    _job(store, "4", fit=90, with_draft=True)   # has draft, skipped
    _job(store, "5", fit=88, closed=True)       # closed, skipped
    out = actions_lib.gen_review_high_fit_jobs(store)
    keys = {a.target_id for a in out}
    assert keys == {"test:1", "test:2"}
    severities = {a.target_id: a.severity for a in out}
    assert severities["test:1"] == "urgent"
    assert severities["test:2"] == "normal"


def test_gen_review_idempotent(store):
    _job(store, "1", fit=85)
    actions_lib.gen_review_high_fit_jobs(store)
    actions_lib.gen_review_high_fit_jobs(store)
    rows = actions_lib.list_actions(store, kind="review_job")
    assert len(rows) == 1  # not duplicated


def test_gen_send_drafts(store):
    _job(store, "1", fit=80, with_draft=True)  # eligible
    _job(store, "2", fit=80)                   # no draft, skipped
    _job(store, "3", fit=80, with_draft=True, closed=True)  # closed, skipped
    out = actions_lib.gen_send_drafts(store)
    assert {a.target_id for a in out} == {"test:1"}


def test_gen_stale_applications(store):
    from career_os.tracker import record_application
    k1 = _job(store, "stuck")
    k2 = _job(store, "fresh")
    record_application(store, k1, stage="sent")
    record_application(store, k2, stage="sent")
    # Backdate stuck one's updated_at to 14 days ago.
    with store._conn() as c:
        c.execute(
            "UPDATE applications SET updated_at = ? WHERE job_key = ?",
            ((datetime.now(UTC) - timedelta(days=14)).isoformat(), k1),
        )
    out = actions_lib.gen_stale_applications(store, days=7)
    assert {a.target_id for a in out} == {k1}


def test_gen_publish_ready_posts(store):
    from career_os.dashboard import posts as posts_lib
    p1 = posts_lib.add_post(store, title="Ready post", channel="blog")
    p2 = posts_lib.add_post(store, title="Drafting", channel="blog")
    posts_lib.set_status(store, p1.id, "ready")
    out = actions_lib.gen_publish_ready_posts(store)
    assert {a.target_id for a in out} == {str(p1.id)}
    assert p2.id not in {int(a.target_id) for a in out}


# ---- run_generators -----------------------------------------------------

def test_run_generators_returns_counts(store):
    _job(store, "1", fit=85)
    _job(store, "2", fit=80, with_draft=True)
    counts = actions_lib.run_generators(store)
    assert counts["review_high_fit_jobs"] == 1
    # 'send_drafts' picks up the with_draft=True job (no application).
    assert counts["send_drafts"] == 1


def test_run_generators_selective(store):
    _job(store, "1", fit=85)
    _job(store, "2", fit=80, with_draft=True)
    counts = actions_lib.run_generators(store, names=["review_high_fit_jobs"])
    assert "review_high_fit_jobs" in counts
    assert "send_drafts" not in counts


# ---- purge_resolved ------------------------------------------------------

def test_purge_resolved_drops_old(store):
    a = actions_lib.upsert_action(store, kind="x", title="t",
                                  target_kind="t", target_id="1")
    actions_lib.resolve(store, a.id, "dismissed")
    # Backdate resolved_at to 100 days ago.
    with store._conn() as c:
        c.execute(
            "UPDATE actions SET resolved_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=100)).isoformat(), a.id),
        )
    n = actions_lib.purge_resolved(store, older_than_days=90)
    assert n == 1
    # All rows gone.
    assert actions_lib.list_actions(store, status="dismissed") == []


def test_purge_resolved_keeps_recent(store):
    a = actions_lib.upsert_action(store, kind="x", title="t",
                                  target_kind="t", target_id="1")
    actions_lib.resolve(store, a.id, "dismissed")
    n = actions_lib.purge_resolved(store, older_than_days=90)
    assert n == 0
