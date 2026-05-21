"""Outreach targets — pipeline state machine + pitch generator."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from career_os import outreach as out_lib
from career_os.db import Store
from career_os.outreach.generator import (
    NO_FIT_MARKER,
    GeneratedPitch,
    generate_pitch,
)
from career_os.profile import DEFAULT_PROFILE


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'out.db'}")


def _target(store, **overrides):
    defaults = dict(
        name="Smashing Magazine guest post",
        site_url="https://www.smashingmagazine.com",
        category="guest_post",
        value_score=8,
    )
    defaults.update(overrides)
    return out_lib.add_target(store, **defaults)


# ---- add_target ----------------------------------------------------------

def test_add_target_creates_row(store):
    t = _target(store)
    assert t.id > 0
    assert t.site_domain == "smashingmagazine.com"
    assert t.stage == "researching"


def test_blank_name_rejected(store):
    with pytest.raises(ValueError):
        out_lib.add_target(store, name="  ", site_url="https://x",
                           category="podcast")


def test_blank_site_url_rejected(store):
    with pytest.raises(ValueError):
        out_lib.add_target(store, name="x", site_url="", category="podcast")


def test_unknown_category_rejected(store):
    with pytest.raises(ValueError):
        out_lib.add_target(store, name="x", site_url="https://x",
                           category="myspace")


def test_value_score_range(store):
    with pytest.raises(ValueError):
        out_lib.add_target(store, name="x", site_url="https://x",
                           category="podcast", value_score=11)
    with pytest.raises(ValueError):
        out_lib.add_target(store, name="x", site_url="https://x",
                           category="podcast", value_score=0)


# ---- advance_stage -------------------------------------------------------

def test_advance_walks_active_chain(store):
    t = _target(store)
    assert out_lib.advance_stage(store, t.id).stage == "pitched"
    assert out_lib.advance_stage(store, t.id).stage == "replied"
    assert out_lib.advance_stage(store, t.id).stage == "accepted"
    assert out_lib.advance_stage(store, t.id).stage == "published"


def test_advance_to_specific_stage(store):
    t = _target(store)
    out_lib.advance_stage(store, t.id, to="declined")
    refreshed = out_lib.get_target(store, t.id)
    assert refreshed.stage == "declined"


def test_advance_rejected_on_unknown_stage(store):
    t = _target(store)
    with pytest.raises(out_lib.StageTransitionError):
        out_lib.advance_stage(store, t.id, to="completely-made-up")


def test_terminal_blocks_advance(store):
    t = _target(store)
    out_lib.advance_stage(store, t.id, to="published")
    with pytest.raises(out_lib.StageTransitionError):
        out_lib.advance_stage(store, t.id)


def test_pitched_stage_stamps_pitched_at(store):
    t = _target(store)
    out_lib.advance_stage(store, t.id, to="pitched")
    refreshed = out_lib.get_target(store, t.id)
    assert refreshed.pitched_at is not None


def test_published_stage_stamps_published_at(store):
    t = _target(store)
    out_lib.advance_stage(store, t.id, to="published")
    refreshed = out_lib.get_target(store, t.id)
    assert refreshed.published_at is not None


# ---- update_target -------------------------------------------------------

def test_update_target_partial(store):
    t = _target(store)
    new = out_lib.update_target(
        store, t.id, value_score=10, contact="hello@smashing.com",
    )
    assert new.value_score == 10
    assert new.contact == "hello@smashing.com"
    # Original fields untouched.
    assert new.name == t.name


def test_update_target_pitch_draft(store):
    t = _target(store)
    new = out_lib.update_target(store, t.id, pitch_draft="Hi Smashing —")
    assert new.pitch_draft.startswith("Hi Smashing")


# ---- list filters --------------------------------------------------------

def test_list_filters_by_stage(store):
    a = _target(store, name="A", site_url="https://a/", category="podcast")
    b = _target(store, name="B", site_url="https://b/", category="podcast")
    out_lib.advance_stage(store, a.id, to="pitched")
    pitched_only = out_lib.list_targets(store, stage="pitched")
    assert [t.id for t in pitched_only] == [a.id]
    research_only = out_lib.list_targets(store, stage="researching")
    assert [t.id for t in research_only] == [b.id]


def test_list_filters_by_category(store):
    _target(store, name="A", site_url="https://a/", category="podcast")
    _target(store, name="B", site_url="https://b/", category="guest_post")
    only_pod = out_lib.list_targets(store, category="podcast")
    assert {t.category for t in only_pod} == {"podcast"}


def test_list_orders_by_value(store):
    a = _target(store, name="lo", site_url="https://lo/", value_score=2)
    b = _target(store, name="hi", site_url="https://hi/", value_score=9)
    rows = out_lib.list_targets(store)
    assert [t.id for t in rows] == [b.id, a.id]


# ---- aggregates ----------------------------------------------------------

def test_counts_by_stage(store):
    a = _target(store, name="A", site_url="https://a/", category="podcast")
    _target(store, name="B", site_url="https://b/", category="podcast")
    out_lib.advance_stage(store, a.id, to="pitched")
    counts = out_lib.counts_by_stage(store)
    assert counts["researching"] == 1
    assert counts["pitched"] == 1
    assert counts["published"] == 0


def test_funnel_counts_nested(store):
    _target(store, name="A", site_url="https://a/", category="podcast")
    _target(store, name="B", site_url="https://b/", category="guest_post")
    funnel = out_lib.funnel_counts(store)
    assert funnel["podcast"]["researching"] == 1
    assert funnel["guest_post"]["researching"] == 1
    assert "researching" in funnel["haro"]  # all categories pre-seeded


# ---- pitch generator (dry-run only — no API key needed) -----------------

@pytest.mark.parametrize("category", [
    "podcast", "guest_post", "directory", "haro",
    "roundup", "unlinked_mention",
])
def test_dry_run_generates_non_empty(store, category):
    t = _target(store, name="X", site_url="https://x/", category=category)
    out = generate_pitch(
        api_key=None, target=t, profile=DEFAULT_PROFILE, dry_run=True,
    )
    assert isinstance(out, GeneratedPitch)
    assert out.body
    assert out.model == "dry-run"
    assert not out.is_no_fit


def test_dry_run_no_api_key_falls_through(store):
    t = _target(store)
    out = generate_pitch(api_key=None, target=t, profile=DEFAULT_PROFILE)
    assert out.model == "dry-run"


def test_no_fit_marker_parses(store, monkeypatch):
    from career_os.outreach import generator as gen_mod

    t = _target(store)

    def _fake_call(client, model, system, user_msg):
        return f"{NO_FIT_MARKER} wrong-audience publication]"
    monkeypatch.setattr(gen_mod, "_call_claude", _fake_call)
    out = generate_pitch(
        api_key="sk-junk", target=t, profile=DEFAULT_PROFILE, dry_run=False,
    )
    assert out.is_no_fit is True
    assert "wrong-audience" in (out.no_fit_reason or "")


def test_live_path_returns_pitch(store, monkeypatch):
    from career_os.outreach import generator as gen_mod

    t = _target(store)

    def _fake_call(client, model, system, user_msg):
        return "Hi Smashing — guest pitch body here."
    monkeypatch.setattr(gen_mod, "_call_claude", _fake_call)
    out = generate_pitch(
        api_key="sk-junk", target=t, profile=DEFAULT_PROFILE, dry_run=False,
    )
    assert out.is_no_fit is False
    assert "Hi Smashing" in out.body


def test_prompt_files_exist_for_each_category():
    from career_os.outreach.generator import PROMPTS_DIR
    # Six explicit prompts shipped; remaining categories fall back to
    # guest_post per the loader.
    for cat in (
        "podcast", "guest_post", "directory", "haro",
        "roundup", "unlinked_mention",
    ):
        path = PROMPTS_DIR / f"pitch_{cat}.md"
        assert path.exists(), f"missing {path}"


# ---- stale-pitch action generator + automation --------------------------

def test_gen_stale_outreach_emits(store):
    from career_os import actions as actions_lib
    t = _target(store)
    out_lib.advance_stage(store, t.id, to="pitched")
    # Backdate pitched_at to 14 days ago.
    with store._conn() as c:
        c.execute(
            "UPDATE outreach_targets SET pitched_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=14)).isoformat(), t.id),
        )
    out = actions_lib.gen_stale_outreach(store, days=10)
    assert len(out) == 1
    assert out[0].target_id == str(t.id)


def test_gen_stale_outreach_idempotent(store):
    from career_os import actions as actions_lib
    t = _target(store)
    out_lib.advance_stage(store, t.id, to="pitched")
    with store._conn() as c:
        c.execute(
            "UPDATE outreach_targets SET pitched_at = ? WHERE id = ?",
            ((datetime.now(UTC) - timedelta(days=14)).isoformat(), t.id),
        )
    actions_lib.gen_stale_outreach(store)
    actions_lib.gen_stale_outreach(store)
    rows = actions_lib.list_actions(store, kind="stale_pitch")
    assert len(rows) == 1


def test_outreach_stale_handler_registered():
    from career_os import automations
    assert "outreach_stale_actions" in automations.known_kinds()
