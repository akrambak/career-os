from __future__ import annotations

from career_os.eval import evaluate_fixtures_with, load_fixtures, summarize
from career_os.models import Score
from career_os.profile import DEFAULT_PROFILE


def test_fixtures_load_and_have_required_fields():
    rows = load_fixtures()
    assert len(rows) >= 8
    for r in rows:
        assert "id" in r
        assert "expected" in r
        assert len(r["expected"]) == 2
        assert 0 <= r["expected"][0] <= r["expected"][1] <= 100
        assert "job" in r and "title" in r["job"] and "description" in r["job"]


def test_summarize_with_constant_scorer():
    def always_50(job, profile):
        return Score(job_key=job.key, fit=50, reasoning="x", pros=[], cons=[])
    rows = evaluate_fixtures_with(always_50, DEFAULT_PROFILE)
    s = summarize(rows)
    assert s["n"] == len(rows)
    assert s["mean_fit"] == 50.0
    assert s["distribution_70_plus"] == 0


def test_stub_scorer_calibration_floor():
    """The keyword stub should at least put perfect-fit fixtures above weak-fit ones."""
    from career_os.cli.main import _stub_score_fn
    rows = evaluate_fixtures_with(_stub_score_fn(), DEFAULT_PROFILE)
    by_id = {r.fixture_id: r.actual for r in rows}
    # The strong-fit fixtures should outscore the dealbreaker ones,
    # even with a naive keyword scorer.
    assert by_id["perfect_freelance"] > by_id["onsite_dealbreaker"]
    assert by_id["perfect_ft"] > by_id["irrelevant_marketing"]
