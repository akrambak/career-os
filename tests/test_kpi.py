"""Pillar 3 — KPI registry + snapshot persistence + derived compute."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from career_os.db import Store
from career_os.kpi import (
    KPIS,
    Threshold,
    compute_derived,
    get_snapshot,
    list_recent,
    sync_derived,
    upsert_snapshot,
)
from career_os.models import Channel, JobPost
from career_os.tracker import record_application


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'kpi.db'}")


# ---- registry shape ------------------------------------------------------

def test_registry_has_three_tiers():
    tiers = {k.tier for k in KPIS}
    assert tiers == {1, 2, 3}


def test_registry_has_at_least_one_derived_kpi():
    derived = [k for k in KPIS if k.source == "derived"]
    assert len(derived) >= 1


def test_known_kpis_have_thresholds():
    # Spot-check: every KPI in the user's plan has a decision rule.
    for kpi in KPIS:
        assert kpi.threshold is not None, f"{kpi.key} missing threshold"


# ---- Threshold -----------------------------------------------------------

def test_threshold_gte_green_when_above():
    t = Threshold("gte", 100)
    assert t.is_green(150)
    assert t.is_green(100)
    assert not t.is_green(99)


def test_threshold_lte_green_when_below():
    t = Threshold("lte", 35)
    assert t.is_green(20)
    assert t.is_green(35)
    assert not t.is_green(36)


def test_threshold_display():
    assert Threshold("gte", 50).display() == "≥ 50"
    assert Threshold("lte", 35).display() == "≤ 35"


# ---- Snapshot CRUD -------------------------------------------------------

def test_upsert_snapshot_creates_and_updates(store):
    snap = upsert_snapshot(store, kpi_key="github_stars", value=12)
    assert snap.value == 12
    # Same week, same kpi → upsert replaces.
    snap2 = upsert_snapshot(store, kpi_key="github_stars", value=25)
    assert snap2.value == 25
    assert snap2.id == snap.id


def test_upsert_rejects_unknown_kpi(store):
    with pytest.raises(ValueError):
        upsert_snapshot(store, kpi_key="not_a_real_kpi", value=1)


def test_get_snapshot_returns_none_when_missing(store):
    mon = date(2026, 5, 18)
    assert get_snapshot(store, "github_stars", mon) is None


def test_list_recent_returns_newest_first(store):
    # Seed three weekly snapshots.
    base = date(2026, 5, 4)
    for i in range(3):
        upsert_snapshot(
            store, kpi_key="github_stars", value=10 + i,
            week_start=base + timedelta(weeks=i),
        )
    rows = list_recent(store, "github_stars", weeks=8)
    assert [r.value for r in rows] == [12, 11, 10]


# ---- derived -------------------------------------------------------------

def _seed_job(store, key, channel: Channel = Channel.FT):
    job = JobPost(
        source="test", external_id=key,
        url=f"https://e.com/{key}", title=f"Job {key}", description="d",
        channel=channel,
    )
    store.upsert_job(job)
    return job.key


def test_compute_derived_counts_outreach_this_week(store):
    k1 = _seed_job(store, "1")
    k2 = _seed_job(store, "2")
    record_application(store, k1, stage="sent")
    record_application(store, k2, stage="sent")
    derived = compute_derived(store)
    assert derived["outreach_sent_wk"] == 2


def test_compute_derived_excludes_prior_week(store):
    k1 = _seed_job(store, "1")
    record_application(store, k1, stage="sent")
    # Backdate applied_at to last week.
    with store._conn() as c:
        c.execute(
            "UPDATE applications SET applied_at = ?, updated_at = ? "
            "WHERE job_key = ?",
            ((datetime.now(UTC) - timedelta(days=10)).isoformat(),
             (datetime.now(UTC) - timedelta(days=10)).isoformat(), k1),
        )
    derived = compute_derived(store)
    assert derived["outreach_sent_wk"] == 0


def test_compute_derived_counts_calls_booked(store):
    # Use channel-matching stages: scope_call is freelance, interview is FT.
    k1 = _seed_job(store, "1", channel=Channel.FREELANCE)
    k2 = _seed_job(store, "2", channel=Channel.FT)
    record_application(store, k1, stage="scope_call")
    record_application(store, k2, stage="interview")
    derived = compute_derived(store)
    assert derived["calls_booked_wk"] == 2


def test_sync_derived_writes_snapshots(store):
    _seed_job(store, "1")
    record_application(store, "test:1", stage="sent")
    n = sync_derived(store)
    assert n >= 1
    mon = date.today() - timedelta(days=date.today().weekday())
    snap = get_snapshot(store, "outreach_sent_wk", mon)
    assert snap is not None
    assert snap.source == "derived"
    assert snap.value == 1


# ---- automation handler hookup ------------------------------------------

def test_kpi_handler_registered_on_import():
    # Importing kpi triggers _ensure_automation_handler_registered().
    from career_os import automations
    assert "sync_derived_kpis" in automations.known_kinds()
