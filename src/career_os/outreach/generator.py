"""Claude pitch generator for outreach targets (SEO Feature 2)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

from anthropic import Anthropic, AuthenticationError
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from ..models import Profile
from . import OutreachTarget

logger = logging.getLogger(__name__)

GENERATOR_MODEL = "claude-sonnet-4-6"
NO_FIT_MARKER = "[NO-FIT:"

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "presence" / "prompts"


@dataclass(frozen=True)
class GeneratedPitch:
    category: str
    body: str
    model: str
    is_no_fit: bool
    no_fit_reason: str | None


def generate_pitch(
    api_key: str | None,
    target: OutreachTarget,
    profile: Profile,
    *,
    model: str = GENERATOR_MODEL,
    dry_run: bool = False,
) -> GeneratedPitch:
    """Generate a category-specific pitch for an outreach target."""
    if dry_run or not api_key:
        body = _render_dry_run(target, profile)
        return _wrap(body, target.category, "dry-run")
    system = _load_prompt(target.category)
    user_msg = _render_user_message(target, profile)
    client = Anthropic(api_key=api_key)
    body = _call_claude(client, model, system, user_msg)
    return _wrap(body, target.category, model)


def _wrap(body: str, category: str, model: str) -> GeneratedPitch:
    body = body.strip()
    is_no_fit = body.startswith(NO_FIT_MARKER)
    no_fit_reason: str | None = None
    if is_no_fit:
        try:
            inside = body[len(NO_FIT_MARKER):].split("]", 1)[0].strip()
            no_fit_reason = inside or None
        except Exception:  # noqa: BLE001
            no_fit_reason = None
    return GeneratedPitch(
        category=category, body=body, model=model,
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
        max_tokens=1200,
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user_msg}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def _load_prompt(category: str) -> str:
    path = PROMPTS_DIR / f"pitch_{category}.md"
    if not path.exists():
        # Fall back to guest_post for any uncovered category — the
        # generic editor-pitch shape works for most.
        path = PROMPTS_DIR / "pitch_guest_post.md"
    if not path.exists():
        raise FileNotFoundError(f"missing pitch prompt: {path}")
    return path.read_text(encoding="utf-8")


def _render_user_message(target: OutreachTarget, profile: Profile) -> str:
    return dedent(f"""
        TARGET:
          Name: {target.name}
          Site: {target.site_url}  ({target.site_domain})
          Category: {target.category}
          Contact: {target.contact or '(none)'}
          Pitch angle: {target.pitch_angle or '(none — write a topic-themed lead)'}
          Target backlink URL (ours): {target.target_backlink_url or '(unspecified)'}

        WRITER PROFILE:
          Name: {profile.name}
          Email: me@bak-dev.com
          Headline: {profile.headline}
          Years experience: {profile.years_experience}
          Proven stack: {", ".join(profile.proven_stack)}
          New stack: {", ".join(profile.new_stack)}
          Public artifact: github.com/akrambak/career-os
    """).strip()


def _render_dry_run(target: OutreachTarget, profile: Profile) -> str:
    """Deterministic offline stub — makes the UI usable without an API key."""
    proven = profile.proven_stack[0] if profile.proven_stack else "production"
    new = ", ".join(profile.new_stack[:2]) or "AI agents"
    angle = (
        target.pitch_angle
        or "I saw the recent posts on your site about AI tooling."
    )
    if target.category == "podcast":
        return dedent(f"""\
            Hi —

            {angle} I'd love to come on and talk about what changes when you
            wire Claude SDK into an established {proven} stack (vs. building
            an LLM demo from scratch).

            Background: 8 years shipping {proven} in production, now layering
            {new} on top. Building Career-OS in public.

            Happy to record any week — DM me a calendar link.

            {profile.name}
            me@bak-dev.com
        """).strip()
    if target.category == "directory":
        return dedent("""\
            TITLE: Career-OS · AI agent for the job hunt
            TAGLINE: Auto-scores remote job postings, drafts your outreach,
              tracks the pipeline.
            DESCRIPTION: Career-OS is an open-source AI-agent toolchain for
            engineers running their own job search and freelance pipeline.
            It crawls public boards (RemoteOK, WeWorkRemotely, Remotive, HN),
            scores fit with Claude, drafts tailored outreach, and tracks
            applications through the pipeline.

            Built by Bakhouche Akram (8y production fullstack), free and
            MIT-licensed. github.com/akrambak/career-os.
        """).strip()
    if target.category == "haro":
        return dedent(f"""\
            I'm {profile.name}, a senior {proven} engineer (8y production).
            Direct answer to your query: (replace this with the specific
            response). One thing I'd emphasize: when you wire {new} into an
            existing production system, the failure mode is rarely the AI —
            it's the integration boundary.

            Quote: "The hardest part of shipping AI features isn't the model
            — it's keeping the rest of the system honest about its
            uncertainty."

            More on what I'm building: github.com/akrambak/career-os.

            {profile.name}
            me@bak-dev.com
        """).strip()
    if target.category == "unlinked_mention":
        return dedent(f"""\
            Hi —

            Thanks for mentioning {profile.name} / Career-OS in your post.
            Would you be open to adding a link to {target.target_backlink_url
                                                   or 'github.com/akrambak/career-os'}?
            Happy to return the favor — let me know if there's anything of
            yours I can share with my audience.

            {profile.name}
            me@bak-dev.com
        """).strip()
    # default: guest_post-style
    return dedent(f"""\
        Hi —

        {angle} I'd like to pitch a guest post: "What changes when you wire
        Claude SDK into a {proven} monolith." It'd cover (1) the integration
        boundary, and (2) what falls over in week two of running it in
        production.

        Background: 8 years shipping {proven} in production e-commerce + SMB,
        now layering {new} on top. Career-OS is the public artifact:
        github.com/akrambak/career-os.

        Happy to send a draft outline if useful.

        {profile.name}
        me@bak-dev.com
    """).strip()


__all__ = [
    "GENERATOR_MODEL", "NO_FIT_MARKER",
    "GeneratedPitch", "generate_pitch",
]
