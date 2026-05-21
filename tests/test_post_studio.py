"""Idea → post generator tests."""
from __future__ import annotations

import pytest

from career_os.post_studio import (
    CHANNEL_TARGETS,
    CHANNELS,
    NO_FIT_MARKER,
    GeneratedPost,
    IdeaInput,
    extract_urls,
    generate_from_idea,
)
from career_os.post_studio import generator as gen_mod
from career_os.profile import DEFAULT_PROFILE

# ---- channels constant ---------------------------------------------------

def test_channels_are_blog_linkedin_x():
    assert set(CHANNELS) == {"blog", "linkedin", "x"}


def test_channel_targets_cover_every_channel():
    for c in CHANNELS:
        assert c in CHANNEL_TARGETS
        assert CHANNEL_TARGETS[c]


# ---- URL extraction -----------------------------------------------------

def test_extract_urls_picks_up_http_and_https():
    text = "see https://bak-dev.com and http://example.org/x"
    assert extract_urls(text) == [
        "https://bak-dev.com", "http://example.org/x",
    ]


def test_extract_urls_strips_trailing_punctuation():
    text = "ref: https://bak-dev.com/post."
    assert extract_urls(text) == ["https://bak-dev.com/post"]


def test_extract_urls_dedupes_preserves_order():
    text = "https://a.com x https://b.com y https://a.com"
    assert extract_urls(text) == ["https://a.com", "https://b.com"]


def test_extract_urls_handles_empty():
    assert extract_urls("") == []
    assert extract_urls(None) == []


# ---- dry-run -------------------------------------------------------------

@pytest.mark.parametrize("channel", list(CHANNELS))
def test_dry_run_returns_non_empty_body(channel):
    idea = IdeaInput(
        idea="Streaming Claude tools in prod is harder than the demo.",
        urls=["https://docs.anthropic.com/streaming"],
    )
    out = generate_from_idea(
        api_key=None, idea=idea, channel=channel,
        profile=DEFAULT_PROFILE, dry_run=True,
    )
    assert isinstance(out, GeneratedPost)
    assert out.model == "dry-run"
    assert out.body
    assert not out.is_no_fit


def test_dry_run_when_no_api_key_falls_through():
    idea = IdeaInput(idea="A thought about LLM ops")
    out = generate_from_idea(
        api_key=None, idea=idea, channel="x",
        profile=DEFAULT_PROFILE,  # no dry_run flag — None key triggers it
    )
    assert out.model == "dry-run"


def test_dry_run_x_is_short():
    idea = IdeaInput(idea="Short hot take about Claude.")
    out = generate_from_idea(
        api_key=None, idea=idea, channel="x",
        profile=DEFAULT_PROFILE, dry_run=True,
    )
    assert len(out.body) < 600


def test_dry_run_blog_includes_refs_when_provided():
    idea = IdeaInput(
        idea="Production lessons from streaming Claude.",
        urls=["https://docs.anthropic.com/streaming"],
    )
    out = generate_from_idea(
        api_key=None, idea=idea, channel="blog",
        profile=DEFAULT_PROFILE, dry_run=True,
    )
    assert "https://docs.anthropic.com/streaming" in out.body


# ---- input validation --------------------------------------------------

def test_blank_idea_raises():
    with pytest.raises(ValueError):
        generate_from_idea(
            api_key=None, idea=IdeaInput(idea="   "),
            channel="x", profile=DEFAULT_PROFILE, dry_run=True,
        )


def test_unknown_channel_raises():
    with pytest.raises(ValueError):
        generate_from_idea(
            api_key=None, idea=IdeaInput(idea="x"),
            channel="myspace", profile=DEFAULT_PROFILE, dry_run=True,
        )


# ---- live path mocked --------------------------------------------------

def test_no_fit_marker_parses(monkeypatch):
    def _fake_call(client, model, system, user_msg):
        return f"{NO_FIT_MARKER} off-positioning for the writer]"
    monkeypatch.setattr(gen_mod, "_call_claude", _fake_call)

    out = generate_from_idea(
        api_key="sk-junk", idea=IdeaInput(idea="Crypto airdrop tips"),
        channel="linkedin", profile=DEFAULT_PROFILE, dry_run=False,
    )
    assert out.is_no_fit is True
    assert out.no_fit_reason
    assert "off-positioning" in out.no_fit_reason


def test_live_path_returns_post_body(monkeypatch):
    def _fake_call(client, model, system, user_msg):
        # Sanity: the user message should contain the idea body and the URL.
        assert "Streaming Claude" in user_msg
        assert "https://docs.anthropic.com/x" in user_msg
        return "Generated body about streaming."
    monkeypatch.setattr(gen_mod, "_call_claude", _fake_call)

    out = generate_from_idea(
        api_key="sk-junk",
        idea=IdeaInput(
            idea="Streaming Claude in prod",
            urls=["https://docs.anthropic.com/x"],
        ),
        channel="linkedin", profile=DEFAULT_PROFILE, dry_run=False,
    )
    assert out.is_no_fit is False
    assert "streaming" in out.body
    assert out.model == gen_mod.GENERATOR_MODEL


# ---- prompt files exist -----------------------------------------------

@pytest.mark.parametrize("channel", list(CHANNELS))
def test_prompt_file_exists_for_each_channel(channel):
    path = gen_mod.PROMPTS_DIR / f"generate_from_idea_{channel}.md"
    assert path.exists(), f"missing per-channel prompt: {path}"
    assert path.read_text(encoding="utf-8").strip()
