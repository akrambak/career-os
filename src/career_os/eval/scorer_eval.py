from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median

from ..models import Channel, JobPost, Profile, Score
from ..profile import DEFAULT_PROFILE
from ..scorer import ClaudeScorer

FIXTURES_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "scored_jobs.jsonl"


@dataclass
class EvalRow:
    fixture_id: str
    expected_min: int
    expected_max: int
    actual: int
    reasoning: str
    in_range: bool

    @property
    def deviation(self) -> int:
        if self.in_range:
            return 0
        if self.actual < self.expected_min:
            return self.expected_min - self.actual
        return self.actual - self.expected_max


def load_fixtures(path: Path = FIXTURES_PATH) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(path)
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(json.loads(line))
    return out


def _fixture_to_job(fixture: dict) -> JobPost:
    j = fixture["job"]
    return JobPost(
        source="eval",
        external_id=fixture["id"],
        url=f"https://example.com/eval/{fixture['id']}",
        title=j["title"],
        company=j.get("company"),
        description=j["description"],
        tags=j.get("tags", []),
        channel=Channel(fixture.get("channel", "either")),
        compensation=j.get("compensation"),
    )


def evaluate_fixtures(
    scorer: ClaudeScorer, profile: Profile = DEFAULT_PROFILE,
    fixtures: list[dict] | None = None,
) -> list[EvalRow]:
    fixtures = fixtures or load_fixtures()
    rows: list[EvalRow] = []
    for f in fixtures:
        job = _fixture_to_job(f)
        score = scorer.score(job, profile)
        lo, hi = f["expected"]
        rows.append(
            EvalRow(
                fixture_id=f["id"],
                expected_min=lo,
                expected_max=hi,
                actual=score.fit,
                reasoning=score.reasoning,
                in_range=lo <= score.fit <= hi,
            )
        )
    return rows


def evaluate_fixtures_with(
    score_fn, profile: Profile = DEFAULT_PROFILE,
    fixtures: list[dict] | None = None,
) -> list[EvalRow]:
    """Variant for tests / dry-run: score_fn(job, profile) -> Score."""
    fixtures = fixtures or load_fixtures()
    rows: list[EvalRow] = []
    for f in fixtures:
        job = _fixture_to_job(f)
        score: Score = score_fn(job, profile)
        lo, hi = f["expected"]
        rows.append(
            EvalRow(
                fixture_id=f["id"],
                expected_min=lo,
                expected_max=hi,
                actual=score.fit,
                reasoning=score.reasoning,
                in_range=lo <= score.fit <= hi,
            )
        )
    return rows


def summarize(rows: list[EvalRow]) -> dict:
    if not rows:
        return {"n": 0}
    actuals = [r.actual for r in rows]
    in_range = sum(1 for r in rows if r.in_range)
    return {
        "n": len(rows),
        "in_range": in_range,
        "in_range_pct": round(100 * in_range / len(rows), 1),
        "mean_fit": round(mean(actuals), 1),
        "median_fit": round(median(actuals), 1),
        "max_deviation": max((r.deviation for r in rows), default=0),
        "distribution_70_plus": sum(1 for a in actuals if a >= 70),
        "distribution_30_to_55": sum(1 for a in actuals if 30 <= a <= 55),
    }
