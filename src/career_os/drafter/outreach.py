from __future__ import annotations

import logging
from textwrap import dedent

from anthropic import Anthropic, AuthenticationError
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from ..models import Channel, JobPost, Profile, Score

logger = logging.getLogger(__name__)

DRAFTER_MODEL = "claude-sonnet-4-6"

FT_SYSTEM = dedent(
    """
    You write tailored cover-letter-style outreach for a senior engineer
    applying to a specific full-time role. Output is plain text, 180–260 words,
    no markdown, no headers. The tone is direct and senior — like an engineer
    emailing a hiring manager peer-to-peer, not a candidate begging for a job.

    Required shape (do not violate):
    1. Opening: ONE sentence that names the role + one concrete reason the
       candidate is a match (a real overlap, not generic enthusiasm).
    2. Middle: 2–3 sentences with specific evidence — 8y production work,
       a relevant artifact (the Career-OS repo is fair game when relevant),
       the actual stack overlap. NO bullet points.
    3. Closing: one sentence proposing a 25-min call, including the candidate's
       email me@bak-dev.com.

    Hard rules:
      - NEVER invent metrics or past employers.
      - NEVER say "I'm passionate about..." or "I'd love the opportunity..."
      - DO reference the company by name if known.
      - DO use the suggested_angle from the scorer as the spine of the pitch.

    Return ONLY the message body. No subject line. No sign-off other than the
    candidate's name and email on the last line.
    """
).strip()

FREELANCE_SYSTEM = dedent(
    """
    You write tailored freelance pitches for a senior engineer responding to
    a posted brief (HN "Seeking freelancer?" comment, freelance-board post,
    or DM). Output is plain text, 140–220 words, no markdown.

    Required shape:
    1. Opening: ONE sentence acknowledging the specific problem in the brief
       (paraphrase, don't quote). Show you read it.
    2. Middle: 2–3 sentences pitching a concrete approach + the engineer's
       relevant track record. NAME the stack overlap. Reference 8y in
       production and the Career-OS repo only when it's actually relevant.
    3. Engagement shape: ONE sentence proposing a scope: 2-week sprint,
       fixed price OR retainer. Mention the floor only if the brief implies
       a lower one.
    4. Closing: ONE sentence offering a 25-min scope call + email me@bak-dev.com.

    Hard rules:
      - NEVER quote a fixed dollar number unless the brief gives a range.
      - NEVER agree to <2 weeks or hourly under €60/hr equivalent.
      - DO say no to bad-shape work if the brief is obviously a deal-breaker.
      - DO use the suggested_angle from the scorer.

    Return ONLY the message body, ending with name + email.
    """
).strip()


class OutreachDrafter:
    def __init__(self, api_key: str, model: str = DRAFTER_MODEL):
        self._client = Anthropic(api_key=api_key)
        self._model = model

    def _system(self, channel: Channel) -> str:
        return FREELANCE_SYSTEM if channel == Channel.FREELANCE else FT_SYSTEM

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=20),
        retry=retry_if_not_exception_type((AuthenticationError, ValueError)),
        reraise=True,
    )
    def draft(self, job: JobPost, score: Score, profile: Profile) -> str:
        system = self._system(job.channel)
        user_msg = dedent(f"""
            CANDIDATE PROFILE:
              Name: {profile.name}
              Email: me@bak-dev.com
              Headline: {profile.headline}
              Years experience: {profile.years_experience}
              Proven stack: {", ".join(profile.proven_stack)}
              New stack: {", ".join(profile.new_stack)}
              Public artifact: github.com/akrambak/career-os (build-in-public AI agent)

            ROLE / BRIEF:
              Channel: {job.channel.value}
              Title: {job.title}
              Company / poster: {job.company or "unknown"}
              Location: {job.location or "unspecified"}
              Compensation: {job.compensation or "unspecified"}
              Tags: {", ".join(job.tags) or "none"}
              Description: {job.description[:6000]}

            SCORER VERDICT:
              Fit: {score.fit}/100
              Reasoning: {score.reasoning}
              Pros: {", ".join(score.pros) or "(none flagged)"}
              Cons: {", ".join(score.cons) or "(none flagged)"}
              Suggested angle: {score.suggested_angle or "(scorer left blank)"}
        """).strip()

        resp = self._client.messages.create(
            model=self._model,
            max_tokens=800,
            system=[
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()


def draft_for_job(
    api_key: str, job: JobPost, score: Score, profile: Profile
) -> tuple[str, str]:
    drafter = OutreachDrafter(api_key)
    body = drafter.draft(job, score, profile)
    return body, DRAFTER_MODEL


def render_dry_run(job: JobPost, score: Score, profile: Profile) -> str:
    """Deterministic offline draft — proves the prompt shape without an API key."""
    if job.channel == Channel.FREELANCE:
        opener = (
            f"Saw your brief for {job.title} — sounds like a "
            f"{', '.join(score.pros[:2]) or 'production'}-shaped problem I've shipped before."
        )
        middle = (
            f"Background: {profile.years_experience}y in production fullstack "
            f"(PHP/Laravel/Flutter), now layering Claude SDK + OSS LLMs on top. "
            f"{score.suggested_angle or 'Happy to walk through specifics on a call.'}"
        )
        scope = (
            "Suggested shape: a 2-week scoped sprint at a fixed price, "
            "with a working feature branch you can pull from day 3. "
            "Retainer afterward if it makes sense."
        )
    else:
        opener = (
            f"Re: {job.title} — the {', '.join(score.pros[:2]) or 'stack'} overlap "
            f"with my 8 years of production fullstack work is the reason I'm writing."
        )
        middle = (
            f"{score.suggested_angle or 'I bring real shipping experience.'} "
            f"I'm building Career-OS in public (github.com/akrambak/career-os) — "
            f"an AI-agent toolchain on top of my Laravel/Flutter foundation."
        )
        scope = ""
    closer = (
        "Happy to set up a 25-min call to see if the shape fits.\n\n"
        f"{profile.name}\nme@bak-dev.com"
    )
    return "\n\n".join(p for p in (opener, middle, scope, closer) if p)
