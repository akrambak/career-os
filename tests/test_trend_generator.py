"""Trend → post generator tests."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from career_os.db import Store
from career_os.profile import DEFAULT_PROFILE
from career_os.trends import Trend, upsert_trend
from career_os.trends.generator import (
    CHANNEL_TARGETS,
    CHANNELS,
    NO_FIT_MARKER,
    GeneratedPost,
    generate_post,
)


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'gen.db'}")


def _trend(store) -> Trend:
    return upsert_trend(
        store, source="hn", external_id="42",
        url="https://news.ycombinator.com/item?id=42",
        title="Anthropic releases tool streaming API",
        score=420, comment_count=187,
        summary="Sonnet 4.6 now supports streaming tool calls server-side.",
        tags=["ai", "claude"],
        fetched_at=datetime.now(UTC),
    )


# ---- channels constant ---------------------------------------------------

def test_channels_includes_all_four():
    assert set(CHANNELS) == {"x", "linkedin", "devto", "blog"}


def test_channel_targets_cover_every_channel():
    for c in CHANNELS:
        assert c in CHANNEL_TARGETS
        assert CHANNEL_TARGETS[c]


# ---- dry-run -------------------------------------------------------------

@pytest.mark.parametrize("channel", list(CHANNELS))
def test_dry_run_returns_non_empty_body(store, channel):
    trend = _trend(store)
    out = generate_post(
        api_key=None, trend=trend, channel=channel,
        profile=DEFAULT_PROFILE, dry_run=True,
    )
    assert isinstance(out, GeneratedPost)
    assert out.model == "dry-run"
    assert out.body
    assert not out.is_no_fit
    assert trend.title in out.body or trend.title.split()[0] in out.body


def test_dry_run_when_no_api_key_falls_through(store):
    trend = _trend(store)
    out = generate_post(
        api_key=None, trend=trend, channel="x",
        profile=DEFAULT_PROFILE,    # no dry_run flag — None key triggers it
    )
    assert out.model == "dry-run"


def test_dry_run_x_is_short(store):
    """X dry-run should be a single tweet, well under 600 chars."""
    trend = _trend(store)
    out = generate_post(
        api_key=None, trend=trend, channel="x",
        profile=DEFAULT_PROFILE, dry_run=True,
    )
    assert len(out.body) < 600


def test_dry_run_devto_has_code_block(store):
    trend = _trend(store)
    out = generate_post(
        api_key=None, trend=trend, channel="devto",
        profile=DEFAULT_PROFILE, dry_run=True,
    )
    assert "```" in out.body


# ---- unknown channel -----------------------------------------------------

def test_unknown_channel_raises(store):
    trend = _trend(store)
    with pytest.raises(ValueError):
        generate_post(
            api_key=None, trend=trend, channel="myspace",
            profile=DEFAULT_PROFILE, dry_run=True,
        )


# ---- no-fit detection (live path mocked) --------------------------------

def test_no_fit_marker_parses(store, monkeypatch):
    """If Claude returns '[NO-FIT: reason]', we surface it correctly."""
    from career_os.trends import generator

    trend = _trend(store)

    def _fake_call(client, model, system, user_msg):
        return f"{NO_FIT_MARKER} off-topic for the user's stack]"
    monkeypatch.setattr(generator, "_call_claude", _fake_call)

    # Patch Anthropic so instantiation doesn't actually require an API key
    # at network time. We can pass a junk string — the patched _call_claude
    # never uses the client.
    out = generate_post(
        api_key="sk-junk-not-real", trend=trend, channel="x",
        profile=DEFAULT_PROFILE, dry_run=False,
    )
    assert out.is_no_fit is True
    assert out.no_fit_reason is not None
    assert "off-topic" in out.no_fit_reason


def test_live_path_returns_non_no_fit(store, monkeypatch):
    from career_os.trends import generator

    trend = _trend(store)

    def _fake_call(client, model, system, user_msg):
        return "A perfectly fine generated post body."
    monkeypatch.setattr(generator, "_call_claude", _fake_call)

    out = generate_post(
        api_key="sk-junk-not-real", trend=trend, channel="linkedin",
        profile=DEFAULT_PROFILE, dry_run=False,
    )
    assert out.is_no_fit is False
    assert out.no_fit_reason is None
    assert "perfectly fine" in out.body
    assert out.model == generator.GENERATOR_MODEL


# ---- prompt files exist -------------------------------------------------

@pytest.mark.parametrize("channel", list(CHANNELS))
def test_prompt_file_exists_for_each_channel(channel):
    from career_os.trends.generator import PROMPTS_DIR
    path = PROMPTS_DIR / f"generate_post_{channel}.md"
    assert path.exists(), f"missing per-channel prompt: {path}"
    assert path.read_text(encoding="utf-8").strip()
