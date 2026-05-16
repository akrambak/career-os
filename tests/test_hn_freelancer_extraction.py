from __future__ import annotations

from career_os.scrapers.hn_freelancer import _extract_fields


def test_extracts_laravel_and_budget():
    text = (
        "SEEKING FREELANCER | REMOTE | Need a Laravel + Vue contractor to add "
        "an AI-powered search feature. Budget around $80-$120/hr. Contact: "
        "founder@startup.io"
    )
    out = _extract_fields(text)
    assert "laravel" in out["stack"]
    assert "vue" in out["stack"]
    assert "ai" in out["stack"]
    assert out["budget"] and "$80" in out["budget"]
    assert out["location"] in ("REMOTE", "Remote", "REMOTE ONLY")
    assert out["contact"] == "founder@startup.io"


def test_no_false_positive_substring_match():
    # "go" as part of "google" must NOT count as a stack hit
    text = "SEEKING FREELANCER. Need help integrating with Google APIs."
    out = _extract_fields(text)
    assert "go" not in out["stack"]
    assert "golang" not in out["stack"]


def test_euro_budget_picked_up():
    text = "SEEKING FREELANCER | Senior Python dev, €600/day, remote EU."
    out = _extract_fields(text)
    assert "python" in out["stack"]
    assert out["budget"] and "€600" in out["budget"]
