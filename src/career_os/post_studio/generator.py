"""Claude-driven post generator from a free-form idea + optional URLs.

Distinct from `career_os.trends.generator` (which is anchored on a Trend
row). Inputs here are user-provided: an idea/angle plus any URLs that
give the model concrete references. Output is a per-channel post body.

`--dry-run` (offline) returns a deterministic stub so the page remains
usable without an API key.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent

from anthropic import Anthropic, AuthenticationError
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..models import Profile

logger = logging.getLogger(__name__)

GENERATOR_MODEL = "claude-sonnet-4-6"

CHANNELS: tuple[str, ...] = ("blog", "linkedin", "x")

CHANNEL_TARGETS = {
    "blog": "800–1500 words",
    "linkedin": "180–280 words",
    "x": "180–280 chars OR 3–5 tweet thread",
}

NO_FIT_MARKER = "[NO-FIT:"

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "presence" / "prompts"

_URL_RE = re.compile(r"https?://[^\s<>\"'`)]+", re.IGNORECASE)


@dataclass(frozen=True)
class IdeaInput:
    """User-supplied seed for the generator."""

    idea: str
    urls: list[str] = field(default_factory=list)
    angle: str | None = None
    audience: str | None = None


@dataclass(frozen=True)
class GeneratedPost:
    channel: str
    body: str
    model: str
    is_no_fit: bool
    no_fit_reason: str | None


def extract_urls(text: str) -> list[str]:
    """Pull http(s) URLs out of free-form text. De-duplicates, preserves order."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _URL_RE.findall(text):
        clean = match.rstrip(".,);:")
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def generate_from_idea(
    api_key: str | None,
    idea: IdeaInput,
    channel: str,
    profile: Profile,
    *,
    model: str = GENERATOR_MODEL,
    dry_run: bool = False,
) -> GeneratedPost:
    if channel not in CHANNELS:
        raise ValueError(
            f"unknown channel {channel!r}, expected one of {CHANNELS}"
        )
    if not idea.idea.strip():
        raise ValueError("idea text is required")

    if dry_run or not api_key:
        body = _render_dry_run(idea, channel, profile)
        return _wrap(body, channel, model="dry-run")

    system = _load_prompt(channel)
    user_msg = _render_user_message(idea, profile)
    client = Anthropic(api_key=api_key)
    body = _call_claude(client, model, system, user_msg)
    return _wrap(body, channel, model)


def _wrap(body: str, channel: str, model: str) -> GeneratedPost:
    body = body.strip()
    is_no_fit = body.startswith(NO_FIT_MARKER)
    no_fit_reason: str | None = None
    if is_no_fit:
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
            {"type": "text", "text": system,
             "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user_msg}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _load_prompt(channel: str) -> str:
    path = PROMPTS_DIR / f"generate_from_idea_{channel}.md"
    if not path.exists():
        raise FileNotFoundError(
            f"missing per-channel prompt: {path}. Add it before generating."
        )
    return path.read_text(encoding="utf-8")


def _render_user_message(idea: IdeaInput, profile: Profile) -> str:
    urls_block = (
        "\n".join(f"  - {u}" for u in idea.urls) if idea.urls else "  (none)"
    )
    angle_line = f"  Angle: {idea.angle}\n" if idea.angle else ""
    audience_line = f"  Audience: {idea.audience}\n" if idea.audience else ""
    return dedent(f"""
        IDEA:
          Body: {idea.idea.strip()}
        {angle_line}{audience_line}  References:
        {urls_block}

        WRITER PROFILE:
          Name: {profile.name}
          Headline: {profile.headline}
          Years experience: {profile.years_experience}
          Proven stack: {", ".join(profile.proven_stack)}
          New stack: {", ".join(profile.new_stack)}
          Public artifact: github.com/akrambak/career-os
    """).strip()


def _render_dry_run(
    idea: IdeaInput, channel: str, profile: Profile,
) -> str:
    """Deterministic offline stub. Echoes the idea + URLs back so the UI
    is testable without an API key."""
    first_line = idea.idea.strip().splitlines()[0] if idea.idea.strip() else ""
    hook = first_line.rstrip(".") + "."
    stack_hint = ", ".join(profile.new_stack[:2]) or "AI agents"
    proven = profile.proven_stack[0] if profile.proven_stack else "production"
    refs = "\n".join(f"- {u}" for u in idea.urls) if idea.urls else "(no refs)"

    if channel == "x":
        return (
            f"{hook} From an {proven} shop layering {stack_hint}: "
            f"the part that matters isn't the demo, it's the second week. "
            f"More soon."
        )
    if channel == "linkedin":
        return dedent(f"""\
            {hook}

            8 years shipping {proven} tells me the test isn't the demo — it's
            the second week. {stack_hint} integrations look great until the
            first cold deploy.

            Trying this in a small slice of Career-OS — failure modes
            documented in public.

            What's the part that's already breaking on you?
        """).strip()
    # blog
    return dedent(f"""\
        # {first_line or 'Untitled idea'}

        A one-paragraph lead would go here — set the stakes in 3-4 sentences.

        ## What I'm thinking about

        {idea.idea.strip()}

        ## References

        {refs}

        ## What it changes for {stack_hint}

        Replace with the concrete production impact for an {proven} shop.

        ## What's next

        Building in public on github.com/akrambak/career-os.
    """).strip()


__all__ = [
    "CHANNELS", "CHANNEL_TARGETS", "GENERATOR_MODEL", "NO_FIT_MARKER",
    "GeneratedPost", "IdeaInput",
    "generate_from_idea", "extract_urls",
]
