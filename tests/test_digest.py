from __future__ import annotations

from career_os.digest import render_digest
from career_os.models import Channel, JobPost, Score


def test_render_empty():
    md = render_digest([])
    assert "No scored jobs" in md


def test_render_freelance_row():
    job = JobPost(
        source="hn_freelancer",
        external_id="42",
        url="https://news.ycombinator.com/item?id=42",
        title="Looking for Laravel + LLM contractor",
        company="someuser",
        description="Need a contractor to add AI search to our Laravel app.",
        channel=Channel.FREELANCE,
        tags=["freelance", "hn"],
    )
    score = Score(
        job_key=job.key, fit=84, reasoning="Direct Laravel + LLM match.",
        pros=["laravel", "llm"], cons=["scope unclear"],
        suggested_angle="Lead with 8y Laravel + recent Claude SDK work.",
    )
    md = render_digest([(job, score)])
    assert "[84]" in md
    assert "freelance" in md
    assert "Angle:" in md
