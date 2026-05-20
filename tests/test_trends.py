"""Trend feed data layer — CRUD, signal scoring, upsert idempotency."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from career_os.db import Store
from career_os.profile import DEFAULT_PROFILE
from career_os.trends import (
    compute_signal_score,
    counts_by_source,
    get_trend,
    list_trends,
    mark_used,
    purge_old,
    recompute_all_signals,
    upsert_trend,
)


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'trends.db'}")


# ---- signal score --------------------------------------------------------

def test_signal_score_zero_when_nothing():
    s = compute_signal_score(
        score=0, comment_count=0,
        fetched_at=datetime.now(UTC),
        title="hello", tags=[],
    )
    assert s == 0.0


def test_signal_score_increases_with_points():
    fresh = datetime.now(UTC)
    a = compute_signal_score(score=50, comment_count=10, fetched_at=fresh,
                             title="x", tags=[])
    b = compute_signal_score(score=500, comment_count=10, fetched_at=fresh,
                             title="x", tags=[])
    assert b > a


def test_signal_score_decays_with_age():
    fresh = datetime.now(UTC)
    old = datetime.now(UTC) - timedelta(hours=120)
    a = compute_signal_score(score=100, comment_count=20, fetched_at=fresh,
                             title="x", tags=[])
    b = compute_signal_score(score=100, comment_count=20, fetched_at=old,
                             title="x", tags=[])
    assert b < a


def test_signal_score_zero_past_horizon():
    # >168h old → recency_factor = 0.
    ancient = datetime.now(UTC) - timedelta(days=14)
    s = compute_signal_score(score=999, comment_count=999,
                             fetched_at=ancient, title="x", tags=[])
    assert s == 0.0


def test_signal_score_topic_boost():
    fresh = datetime.now(UTC)
    no_match = compute_signal_score(
        score=100, comment_count=20, fetched_at=fresh,
        title="something boring", tags=[],
    )
    with_match = compute_signal_score(
        score=100, comment_count=20, fetched_at=fresh,
        title="Claude SDK ships streaming tools", tags=[],
        profile=DEFAULT_PROFILE,
    )
    assert with_match > no_match


# ---- upsert + dedup ------------------------------------------------------

def test_upsert_new_trend_creates_row(store):
    t = upsert_trend(
        store, source="hn", external_id="123",
        url="https://news.ycombinator.com/item?id=123",
        title="Anthropic releases tool streaming",
        score=420, comment_count=187, tags=["ai", "claude"],
    )
    assert t.id > 0
    assert t.signal_score > 0
    rows = list_trends(store, min_signal=0.0)
    assert len(rows) == 1


def test_upsert_same_source_id_updates_in_place(store):
    a = upsert_trend(
        store, source="hn", external_id="42",
        url="https://h/42", title="t", score=10, comment_count=2,
    )
    b = upsert_trend(
        store, source="hn", external_id="42",
        url="https://h/42", title="t", score=200, comment_count=80,
    )
    assert a.id == b.id
    assert b.score == 200
    assert b.signal_score > a.signal_score
    assert len(list_trends(store, min_signal=0.0)) == 1


def test_upsert_rejects_unknown_source(store):
    with pytest.raises(ValueError):
        upsert_trend(store, source="tiktok", url="x", title="y")


# ---- list filters --------------------------------------------------------

def test_list_trends_filters_by_source(store):
    upsert_trend(store, source="hn", external_id="1", url="https://a", title="A")
    upsert_trend(store, source="devto", external_id="2", url="https://b", title="B")
    hn_only = list_trends(store, source="hn", min_signal=0.0)
    assert {t.source for t in hn_only} == {"hn"}


def test_list_trends_filters_by_min_signal(store):
    fresh = datetime.now(UTC)
    upsert_trend(store, source="hn", external_id="lo", url="https://a",
                 title="weak", score=1, comment_count=0, fetched_at=fresh)
    upsert_trend(store, source="hn", external_id="hi", url="https://b",
                 title="strong", score=500, comment_count=200,
                 fetched_at=fresh)
    high_only = list_trends(store, min_signal=2.0)
    assert {t.external_id for t in high_only} == {"hi"}


def test_list_trends_hides_used_by_default(store):
    t = upsert_trend(store, source="hn", external_id="1", url="https://a",
                    title="used", score=100, comment_count=20)
    mark_used(store, t.id)
    visible = list_trends(store)
    assert visible == []
    # But include them when explicitly asked.
    all_rows = list_trends(store, hide_used=False)
    assert len(all_rows) == 1


def test_list_trends_orders_by_signal_desc(store):
    fresh = datetime.now(UTC)
    upsert_trend(store, source="hn", external_id="lo", url="https://a",
                 title="weak", score=10, fetched_at=fresh)
    upsert_trend(store, source="hn", external_id="hi", url="https://b",
                 title="strong", score=500, comment_count=100, fetched_at=fresh)
    rows = list_trends(store, min_signal=0.0)
    assert rows[0].external_id == "hi"
    assert rows[1].external_id == "lo"


# ---- mark_used -----------------------------------------------------------

def test_mark_used_sets_timestamp(store):
    t = upsert_trend(store, source="hn", external_id="1",
                    url="https://a", title="x")
    updated = mark_used(store, t.id)
    assert updated.used_at is not None


def test_mark_used_idempotent_preserves_original(store):
    t = upsert_trend(store, source="hn", external_id="1",
                    url="https://a", title="x")
    first = mark_used(store, t.id)
    second = mark_used(store, t.id)
    assert second.used_at == first.used_at


# ---- counts / recompute / purge -----------------------------------------

def test_counts_by_source(store):
    upsert_trend(store, source="hn", external_id="1", url="https://a", title="A")
    upsert_trend(store, source="hn", external_id="2", url="https://b", title="B")
    upsert_trend(store, source="devto", external_id="3", url="https://c", title="C")
    counts = counts_by_source(store)
    assert counts["hn"] == 2
    assert counts["devto"] == 1
    assert counts["tavily"] == 0


def test_recompute_all_signals_walks_table(store):
    upsert_trend(store, source="hn", external_id="1", url="https://a",
                title="x", score=100, comment_count=20)
    n = recompute_all_signals(store, profile=DEFAULT_PROFILE)
    assert n == 1


def test_purge_old_drops_unused_old_rows(store):
    t = upsert_trend(store, source="hn", external_id="ancient",
                    url="https://a", title="old", score=10)
    # Backdate fetched_at to 90 days ago.
    with store._conn() as c:
        c.execute(
            "UPDATE trends SET fetched_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=90)).isoformat(), t.id),
        )
    n = purge_old(store, older_than_days=30)
    assert n == 1


def test_purge_old_keeps_used_trends_even_if_old(store):
    t = upsert_trend(store, source="hn", external_id="ancient_used",
                    url="https://a", title="old but used", score=10)
    mark_used(store, t.id)
    with store._conn() as c:
        c.execute(
            "UPDATE trends SET fetched_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=90)).isoformat(), t.id),
        )
    n = purge_old(store, older_than_days=30)
    assert n == 0
    assert get_trend(store, t.id).id == t.id
