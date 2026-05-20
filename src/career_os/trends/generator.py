"""Claude-driven post generator from a trend.

For each channel (x / linkedin / devto / blog), the system prompt is
loaded from `presence/prompts/generate_post_<channel>.md`. The trend's
title + URL + summary + tags become the user message. Output is the
post body — the dashboard pipes it into `posts.add_post()` with
`trend_id` set.

`--dry-run` (offline) returns a template-based stub so the page is still
usable without an API key or while developing.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

from anthropic import Anthropic, AuthenticationError
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from ..models import Profile
from . import Trend

logger = logging.getLogger(__name__)

GENERATOR_MODEL = "claude-sonnet-4-6"

CHANNELS: tuple[str, ...] = ("x", "linkedin", "devto", "blog")

# Per-channel approximate word/char targets — surfaced to the user for UI
# expectations. The model is told this in the system prompt; we just echo it.
CHANNEL_TARGETS = {
    "x": "180–280 chars OR 3–5 tweet thread",
    "linkedin": "180–280 words",
    "devto": "600–900 words",
    "blog": "800–1500 words",
}

NO_FIT_MARKER = "[NO-FIT:"

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "presence" / "prompts"


@dataclass(frozen=True)
class GeneratedPost:
    channel: str
    body: str
    model: str            # e.g. 'claude-sonnet-4-6' or 'dry-run'
    is_no_fit: bool       # True if Claude refused (post.body starts with [NO-FIT:)
    no_fit_reason: str | None


# ---- public API ----------------------------------------------------------

def generate_post(
    api_key: str | None,
    trend: Trend,
    channel: str,
    profile: Profile,
    *,
    model: str = GENERATOR_MODEL,
    dry_run: bool = False,
) -> GeneratedPost:
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}, expected one of {CHANNELS}")
    if dry_run or not api_key:
        body = _render_dry_run(trend, channel, profile)
        return _wrap(body, channel, model="dry-run")

    system = _load_prompt(channel)
    user_msg = _render_user_message(trend, profile)
    client = Anthropic(api_key=api_key)
    body = _call_claude(client, model, system, user_msg)
    return _wrap(body, channel, model)


def _wrap(body: str, channel: str, model: str) -> GeneratedPost:
    body = body.strip()
    is_no_fit = body.startswith(NO_FIT_MARKER)
    no_fit_reason: str | None = None
    if is_no_fit:
        # Extract '<reason>' from '[NO-FIT: <reason>]' (best effort).
        try:
            inside = body[len(NO_FIT_MARKER):].split("]", 1)[0].strip()
            no_fit_reason = inside or None
        except Exception:  # noqa: BLE001
            no_fit_reason = None
    return GeneratedPost(
        channel=channel, body=body, model=model,
        is_no_fit=is_no_fit, no_fit_reason=no_fit_reason,
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=20),
    retry=retry_if_not_exception_type((AuthenticationError, ValueError)),
    reraise=True,
)
def _call_claude(
    client: Anthropic, model: str, system: str, user_msg: str,
) -> str:
    resp = client.messages.create(
        model=model,
        max_tokens=2000,
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user_msg}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


# ---- prompt loading ------------------------------------------------------

def _load_prompt(channel: str) -> str:
    path = PROMPTS_DIR / f"generate_post_{channel}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"missing per-channel prompt: {path}. Add it before generating."
        )
    return path.read_text(encoding="utf-8")


def _render_user_message(trend: Trend, profile: Profile) -> str:
    tags_line = ", ".join(trend.tags) if trend.tags else "(none)"
    summary = (trend.summary or "(no summary scraped)").strip()
    return dedent(f"""
        TREND:
          Source: {trend.source}
          Title: {trend.title}
          URL: {trend.url}
          Score: {trend.score}  ({trend.comment_count} comments)
          Tags: {tags_line}
          Summary: {summary[:1200]}

        WRITER PROFILE:
          Name: {profile.name}
          Headline: {profile.headline}
          Years experience: {profile.years_experience}
          Proven stack: {", ".join(profile.proven_stack)}
          New stack: {", ".join(profile.new_stack)}
          Public artifact: github.com/akrambak/career-os
    """).strip()


# ---- dry-run template ----------------------------------------------------

def _render_dry_run(trend: Trend, channel: str, profile: Profile) -> str:
    """Deterministic offline stub. Shows the prompt shape + makes the UI
    usable without an API key."""
    hook = trend.title.rstrip(".") + "."
    stack_hint = ", ".join(profile.new_stack[:2]) or "AI agents"
    proven = profile.proven_stack[0] if profile.proven_stack else "production"

    if channel == "x":
        return (
            f"{hook} What this actually changes for a {proven} shop "
            f"shipping {stack_hint}: not as much as the thread implies. "
            f"What I'm watching."
        )
    if channel == "linkedin":
        return dedent(f"""\
            {hook}

            8 years shipping {proven} in production tells me the real test isn't
            the demo — it's the second week, when the {stack_hint} integration
            outlives its first deploy.

            What I'm trying this week: pulling {trend.title.lower()[:40]} into a
            small slice of the Career-OS pipeline, with the failure modes
            documented in public.

            If you're integrating something similar — what's the part that's
            already breaking on you?
        """).strip()
    if channel == "devto":
        return dedent(f"""\
            TL;DR — {trend.title}. Here's what changes for a {proven} shop, and
            what I'm trying this week.

            ## What it is

            See the announcement: {trend.url}

            ## What it changes for {stack_hint}

            (Concrete production impact — replace with your actual experiment.)

            ```python
            # placeholder — the live generator fills this in with a real example
            print("hello, {channel}")
            ```

            ## What's next

            Pull on github.com/akrambak/career-os for the in-public build.
        """).strip()
    # blog
    return dedent(f"""\
        # {trend.title}

        A one-paragraph lead would go here — set the stakes in 3-4 sentences.

        ## What it is

        Reference: {trend.url}

        ## What it changes for {stack_hint}

        Replace with the concrete production impact.

        ## What we tried

        ```python
        # placeholder code block
        ```

        ## What's next

        Building in public on github.com/akrambak/career-os.
    """).strip()


__all__ = [
    "CHANNELS", "CHANNEL_TARGETS", "GENERATOR_MODEL", "NO_FIT_MARKER",
    "GeneratedPost", "generate_post",
]
