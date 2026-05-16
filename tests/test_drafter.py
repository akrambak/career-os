from __future__ import annotations

from career_os.db import Store
from career_os.drafter import render_dry_run
from career_os.models import Channel, JobPost, Score
from career_os.profile import DEFAULT_PROFILE


def _ft_job() -> JobPost:
    return JobPost(
        source="weworkremotely",
        external_id="acme-fs",
        url="https://example.com/jobs/acme",
        title="Senior Fullstack Engineer",
        company="Acme",
        description="Laravel + Vue shop hiring an AI-savvy senior.",
        tags=["laravel", "vue", "ai"],
        channel=Channel.FT,
    )


def _freelance_job() -> JobPost:
    return JobPost(
        source="hn_freelancer",
        external_id="42",
        url="https://news.ycombinator.com/item?id=42",
        title="Need Laravel + LLM contractor",
        company="founder42",
        description="Adding AI search to our Laravel app. 4-6 weeks of work.",
        tags=["freelance", "hn"],
        channel=Channel.FREELANCE,
    )


def _score(job: JobPost, fit: int = 78) -> Score:
    return Score(
        job_key=job.key, fit=fit,
        reasoning="Strong stack overlap.",
        pros=["laravel", "ai"],
        cons=[],
        suggested_angle="Lead with the Laravel + Claude SDK overlap.",
    )


def test_freelance_dry_run_contains_scope_line():
    job = _freelance_job()
    text = render_dry_run(job, _score(job), DEFAULT_PROFILE)
    assert "2-week" in text
    assert "me@bak-dev.com" in text
    assert "Bakhouche Akram" in text


def test_ft_dry_run_no_scope_line():
    job = _ft_job()
    text = render_dry_run(job, _score(job), DEFAULT_PROFILE)
    assert "2-week" not in text
    assert "me@bak-dev.com" in text


def test_store_round_trips_draft(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'db.sqlite'}")
    job = _ft_job()
    store.upsert_job(job)
    store.save_score(_score(job))
    body = render_dry_run(job, _score(job), DEFAULT_PROFILE)
    store.save_draft(job.key, fmt="ft", body=body, model="dry-run")
    out = store.get_draft(job.key)
    assert out is not None
    assert out["format"] == "ft"
    assert "me@bak-dev.com" in out["body"]
