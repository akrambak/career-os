"""Pillar 4 — today's focus aggregator."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from career_os import actions as actions_lib
from career_os.dashboard import posts as posts_lib
from career_os.dashboard.focus import compute_focus
from career_os.dashboard.todos import add_custom
from career_os.db import Store
from career_os.models import Channel, JobPost
from career_os.tracker import record_application


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'focus.db'}")


def _job(store, key):
    job = JobPost(
        source="test", external_id=key, url=f"https://e.com/{key}",
        title=f"Job {key}", description="d", channel=Channel.FT,
    )
    store.upsert_job(job)
    return job.key


# ---- empty case ----------------------------------------------------------

def test_compute_focus_returns_inbox_zero_when_empty(store):
    focus = compute_focus(store)
    assert focus.total_actions == 0
    assert focus.p0_todos_due_week == 0
    assert "Inbox zero" in focus.headline


# ---- actions counts ------------------------------------------------------

def test_focus_counts_actions_by_severity(store):
    actions_lib.upsert_action(store, kind="x", title="a", severity="urgent",
                              target_kind="t", target_id="1")
    actions_lib.upsert_action(store, kind="x", title="b", severity="urgent",
                              target_kind="t", target_id="2")
    actions_lib.upsert_action(store, kind="x", title="c", severity="normal",
                              target_kind="t", target_id="3")
    focus = compute_focus(store)
    assert focus.urgent_actions == 2
    assert focus.normal_actions == 1
    assert focus.low_actions == 0
    assert focus.total_actions == 3
    assert "🔴 2 urgent" in focus.headline


# ---- p0 todos -----------------------------------------------------------

def test_focus_counts_p0_todos_due_this_week(store):
    today = datetime.now(UTC).date().isoformat()
    in_a_week = (datetime.now(UTC).date() + timedelta(days=6)).isoformat()
    too_far = (datetime.now(UTC).date() + timedelta(days=14)).isoformat()
    add_custom(store, section="Plan", item="A", priority="P0", due_date=today)
    add_custom(store, section="Plan", item="B", priority="P0", due_date=in_a_week)
    add_custom(store, section="Plan", item="C", priority="P0", due_date=too_far)
    add_custom(store, section="Plan", item="D", priority="P1", due_date=today)
    focus = compute_focus(store)
    assert focus.p0_todos_due_week == 2


def test_focus_p0_with_no_due_date_counts(store):
    add_custom(store, section="Plan", item="No due", priority="P0", due_date=None)
    focus = compute_focus(store)
    assert focus.p0_todos_due_week == 1


# ---- posts ready --------------------------------------------------------

def test_focus_counts_posts_ready_to_publish(store):
    p1 = posts_lib.add_post(store, title="ready post", channel="blog")
    posts_lib.set_status(store, p1.id, "ready")
    posts_lib.add_post(store, title="still drafting", channel="blog")
    p3 = posts_lib.add_post(store, title="already shipped", channel="blog")
    posts_lib.set_status(store, p3.id, "posted")
    focus = compute_focus(store)
    assert focus.posts_ready_to_publish == 1


# ---- stale applications -------------------------------------------------

def test_focus_counts_stale_applications(store):
    k1 = _job(store, "stuck")
    k2 = _job(store, "fresh")
    record_application(store, k1, stage="sent")
    record_application(store, k2, stage="sent")
    with store._conn() as c:
        c.execute(
            "UPDATE applications SET updated_at = ? WHERE job_key = ?",
            ((datetime.now(UTC) - timedelta(days=14)).isoformat(), k1),
        )
    focus = compute_focus(store)
    assert focus.stale_applications == 1


def test_focus_excludes_terminal_stages_from_stale(store):
    k1 = _job(store, "won")
    record_application(store, k1, stage="won")
    with store._conn() as c:
        c.execute(
            "UPDATE applications SET updated_at = ? WHERE job_key = ?",
            ((datetime.now(UTC) - timedelta(days=30)).isoformat(), k1),
        )
    focus = compute_focus(store)
    assert focus.stale_applications == 0


# ---- headline priority --------------------------------------------------

def test_headline_prioritizes_urgent_over_p0(store):
    actions_lib.upsert_action(store, kind="x", title="urgent", severity="urgent",
                              target_kind="t", target_id="1")
    add_custom(store, section="Plan", item="P0", priority="P0", due_date=None)
    focus = compute_focus(store)
    assert "urgent" in focus.headline.lower()


def test_headline_falls_through_to_p0_when_no_actions(store):
    add_custom(store, section="Plan", item="P0", priority="P0", due_date=None)
    focus = compute_focus(store)
    assert "P0" in focus.headline
