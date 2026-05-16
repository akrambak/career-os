from __future__ import annotations

import json
import logging
from textwrap import dedent

from anthropic import Anthropic, APIStatusError, AuthenticationError
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from ..db import Store
from ..models import JobPost, Profile, Score

logger = logging.getLogger(__name__)

# Sonnet 4.6 is the right model for high-volume per-job scoring — cheaper
# than Opus, accurate enough for a 0–100 fit judgment with structured output.
SCORER_MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = dedent(
    """
    You are a hiring-fit evaluator for one specific engineer. You read a job
    posting and the engineer's profile, then return a strict JSON object
    judging how good a fit the role is — for the engineer, not the employer.

    Be honest and discriminating. A 70+ score should mean "this is genuinely
    worth applying to today." Most jobs are 30–55. Reserve 85+ for unusually
    aligned matches.

    Penalize hard:
      - On-site or hybrid when the profile is remote-only
      - Stack mismatch where the engineer would be learning the whole job
      - Vague AI/ML buzzword roles with no real product behind them
      - Junior or mid-level roles for a senior profile
      - Hourly freelance gigs below the engineer's stated floor

    Reward:
      - Senior signal in the JD
      - E-commerce, SMB tooling, or developer tooling domain
      - Real product with paying users vs. demo-stage
      - AI/LLM features grounded in something concrete (not "we want to use AI")
      - For freelance: clear scope, retainer/fixed-price, 2+ weeks

    Return ONLY a JSON object — no prose, no markdown fence. Schema:
    {
      "fit": 0-100,
      "reasoning": "2-3 sentence judgment",
      "pros": ["..."],
      "cons": ["..."],
      "suggested_angle": "one sentence on how to pitch yourself for this role,
                         or null if fit < 40"
    }
    """
).strip()


class ClaudeScorer:
    def __init__(self, api_key: str, model: str = SCORER_MODEL):
        self._client = Anthropic(api_key=api_key)
        self._model = model
        self._profile_block: dict | None = None

    def _profile_payload(self, profile: Profile) -> dict:
        return {
            "name": profile.name,
            "headline": profile.headline,
            "years_experience": profile.years_experience,
            "proven_stack": profile.proven_stack,
            "new_stack": profile.new_stack,
            "target_channels": [c.value for c in profile.target_channels],
            "deal_breakers": profile.deal_breakers,
            "nice_to_haves": profile.nice_to_haves,
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=20),
        retry=retry_if_not_exception_type((AuthenticationError, ValueError)),
        reraise=True,
    )
    def score(self, job: JobPost, profile: Profile) -> Score:
        if self._profile_block is None:
            self._profile_block = self._profile_payload(profile)
        user_msg = json.dumps(
            {
                "profile": self._profile_block,
                "job": {
                    "title": job.title,
                    "company": job.company,
                    "location": job.location,
                    "tags": job.tags,
                    "channel": job.channel.value,
                    "compensation": job.compensation,
                    "description": job.description[:8000],
                },
            },
            ensure_ascii=False,
        )
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=600,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        data = json.loads(text)
        return Score(
            job_key=job.key,
            fit=int(data["fit"]),
            reasoning=data["reasoning"],
            pros=list(data.get("pros") or []),
            cons=list(data.get("cons") or []),
            suggested_angle=data.get("suggested_angle"),
        )


def score_pending(
    store: Store,
    scorer: ClaudeScorer,
    profile: Profile,
    limit: int = 50,
) -> int:
    jobs = store.unscored_jobs(limit=limit)
    scored = 0
    for job in jobs:
        try:
            store.save_score(scorer.score(job, profile))
            scored += 1
        except AuthenticationError:
            logger.error(
                "Anthropic API auth failed — check ANTHROPIC_API_KEY in .env. "
                "Aborting after %d scored.", scored,
            )
            raise
        except APIStatusError as exc:
            logger.warning("scoring %s failed (API %s): %s",
                           job.key, exc.status_code, exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("scoring %s failed: %s", job.key, exc)
    return scored
