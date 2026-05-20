"""High-signal trend → review_trend action generator + scan_trends handler."""
from __future__ import annotations

import pytest

from career_os import actions as actions_lib
from career_os import automations as auto_lib
from career_os.db import Store
from career_os.trends import upsert_trend


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'ta.db'}")


def test_gen_high_signal_trends_emits_for_strong(store):
    upsert_trend(
        store, source="hn", external_id="1", url="https://a",
        title="Anthropic releases tool streaming",
        score=500, comment_count=200,
    )
    upsert_trend(
        store, source="hn", external_id="2", url="https://b",
        title="Weak signal", score=1, comment_count=0,
    )
    out = actions_lib.gen_high_signal_trends(store, signal_threshold=1.5)
    target_ids = {a.target_id for a in out}
    assert "1" in target_ids
    assert "2" not in target_ids


def test_gen_high_signal_trends_idempotent(store):
    upsert_trend(
        store, source="hn", external_id="1", url="https://a",
        title="Anthropic releases tool streaming",
        score=500, comment_count=200,
    )
    actions_lib.gen_high_signal_trends(store, signal_threshold=1.5)
    actions_lib.gen_high_signal_trends(store, signal_threshold=1.5)
    rows = actions_lib.list_actions(store, kind="review_trend")
    assert len(rows) == 1


def test_gen_high_signal_trends_skips_used(store):
    t = upsert_trend(
        store, source="hn", external_id="1", url="https://a",
        title="Strong used", score=500, comment_count=200,
    )
    from career_os.trends import mark_used
    mark_used(store, t.id)
    out = actions_lib.gen_high_signal_trends(store, signal_threshold=1.5)
    assert out == []


def test_review_trend_in_GENERATORS():
    names = [name for name, _ in actions_lib.GENERATORS]
    assert "high_signal_trends" in names


def test_scan_trends_handler_registered():
    assert "scan_trends" in auto_lib.known_kinds()


def test_scan_trends_in_default_automations():
    names = [row[0] for row in auto_lib.DEFAULT_AUTOMATIONS]
    assert "scan_trends_4h" in names
