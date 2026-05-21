"""Mention Hunter — data layer + cross-feature converters."""
from __future__ import annotations

import pytest

from career_os import mentions as men_lib
from career_os.db import Store


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'm.db'}")


def _add(store, **overrides):
    defaults = dict(
        source="hn",
        source_url="https://news.ycombinator.com/item?id=42",
        matched_term="bak-dev.com",
        context_snippet="...mentioned bak-dev.com today...",
        has_link_value=False,
    )
    defaults.update(overrides)
    return men_lib.upsert_mention(store, **defaults)


# ---- has_link heuristic --------------------------------------------------

def test_has_link_true_for_known_domain():
    assert men_lib.has_link("Check out https://bak-dev.com/blog") is True


def test_has_link_true_for_repo_path():
    assert men_lib.has_link("see github.com/akrambak/career-os") is True


def test_has_link_false_for_brand_only():
    assert men_lib.has_link("AkBak's project is interesting") is False


def test_has_link_false_for_empty():
    assert men_lib.has_link(None) is False
    assert men_lib.has_link("") is False


# ---- CRUD ----------------------------------------------------------------

def test_upsert_creates_new(store):
    m = _add(store)
    assert m.id > 0
    assert m.status == "open"
    assert m.has_link is False


def test_upsert_is_idempotent_on_same_pair(store):
    a = _add(store, context_snippet="original")
    b = _add(store, context_snippet="updated")
    assert a.id == b.id
    assert b.context_snippet == "updated"
    assert len(men_lib.list_mentions(store)) == 1


def test_upsert_does_not_reopen_resolved(store):
    m = _add(store)
    men_lib.set_status(store, m.id, "dismissed")
    # Re-discovery refresh shouldn't flip status back to open.
    again = _add(store, context_snippet="re-discovered later")
    assert again.status == "dismissed"


def test_upsert_rejects_unknown_source(store):
    with pytest.raises(ValueError):
        men_lib.upsert_mention(
            store, source="twitter",
            source_url="https://x", matched_term="X",
        )


def test_set_status_rejects_unknown_status(store):
    m = _add(store)
    with pytest.raises(ValueError):
        men_lib.set_status(store, m.id, "ghosted")


# ---- list filters --------------------------------------------------------

def test_list_default_only_open(store):
    m = _add(store, source_url="https://a/1")
    _add(store, source_url="https://a/2", matched_term="AkBak")
    men_lib.set_status(store, m.id, "dismissed")
    open_only = men_lib.list_mentions(store)
    assert len(open_only) == 1


def test_list_filters_by_source(store):
    _add(store, source="hn", source_url="https://a/1")
    _add(store, source="devto", source_url="https://b/2")
    hn_only = men_lib.list_mentions(store, source="hn")
    assert {m.source for m in hn_only} == {"hn"}


def test_list_filters_by_has_link(store):
    _add(store, source_url="https://a/1", has_link_value=True)
    _add(store, source_url="https://a/2", has_link_value=False)
    unlinked = men_lib.list_mentions(store, has_link_value=False)
    assert [m.has_link for m in unlinked] == [False]
    linked = men_lib.list_mentions(store, has_link_value=True)
    assert [m.has_link for m in linked] == [True]


# ---- aggregates ----------------------------------------------------------

def test_counts_by_status(store):
    a = _add(store, source_url="https://a/1")
    _add(store, source_url="https://a/2")
    men_lib.set_status(store, a.id, "converted")
    counts = men_lib.counts_by_status(store)
    assert counts["open"] == 1
    assert counts["converted"] == 1
    assert counts["dismissed"] == 0


# ---- cross-feature converters -------------------------------------------

def test_convert_to_backlink_creates_backlinks_row(store):
    from career_os import backlinks as bl_lib
    m = _add(store)
    bl_id = men_lib.convert_to_backlink(
        store, m.id,
        target_url="https://bak-dev.com/blog/x",
        anchor_text="bak-dev.com", rel="dofollow", da_estimate=60,
    )
    bl = bl_lib.get_backlink(store, bl_id)
    assert bl.source_url == m.source_url
    assert bl.target_url == "https://bak-dev.com/blog/x"
    assert bl.discovered_via == "mention_hunter"
    assert bl.status == "live"
    # Mention flipped to 'converted'.
    refreshed = men_lib.get_mention(store, m.id)
    assert refreshed.status == "converted"


def test_to_outreach_target_creates_outreach_row(store):
    from career_os import outreach as out_lib
    m = _add(store)
    target_id = men_lib.to_outreach_target(
        store, m.id,
        pitch_angle="thanks for mentioning",
        value_score=7,
        target_backlink_url="https://github.com/akrambak/career-os",
    )
    t = out_lib.get_target(store, target_id)
    assert t.site_url == m.source_url
    assert t.category == "unlinked_mention"
    assert t.value_score == 7
    assert t.pitch_angle == "thanks for mentioning"
    assert t.stage == "researching"


# ---- action generator ---------------------------------------------------

def test_gen_unlinked_mentions_emits_for_unlinked_only(store):
    from career_os import actions as actions_lib
    _add(store, source="hn", source_url="https://a/1", has_link_value=False)
    _add(store, source="devto", source_url="https://b/2", has_link_value=True)
    out = actions_lib.gen_unlinked_mentions(store)
    assert len(out) == 1
    # HN unlinked → urgent
    assert out[0].severity == "urgent"


def test_gen_unlinked_mentions_idempotent(store):
    from career_os import actions as actions_lib
    _add(store, has_link_value=False)
    actions_lib.gen_unlinked_mentions(store)
    actions_lib.gen_unlinked_mentions(store)
    rows = actions_lib.list_actions(store, kind="unlinked_mention")
    assert len(rows) == 1


def test_mention_scan_handler_registered():
    from career_os import automations
    assert "mention_scan" in automations.known_kinds()


def test_mention_scan_in_default_automations():
    from career_os import automations
    names = [row[0] for row in automations.DEFAULT_AUTOMATIONS]
    assert "mention_scan_daily" in names
