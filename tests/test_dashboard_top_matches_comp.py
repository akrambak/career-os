"""TopMatch surfaces parsed compensation (Tier 1, Upgrade 3 acceptance)."""
from __future__ import annotations

from career_os.dashboard.queries import top_matches
from career_os.db import Store
from career_os.models import Channel, JobPost, Score
from career_os.salary import Compensation, parse


def _store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'db.sqlite'}")


def _seed(store: Store, *, key: str, fit: int, parsed: Compensation | None,
          raw: str | None = None) -> str:
    job = JobPost(
        source="test", external_id=key,
        url=f"https://example.com/{key}", title="Senior Laravel",
        company="Acme", description="desc",
        channel=Channel.FT, compensation=raw,
        parsed_compensation=parsed,
    )
    store.upsert_job(job)
    store.save_score(Score(
        job_key=job.key, fit=fit, reasoning="x",
        pros=[], cons=[], suggested_angle="angle",
    ))
    return job.key


def test_top_matches_returns_parsed_comp_columns(tmp_path):
    store = _store(tmp_path)
    _seed(store, key="1", fit=80, parsed=parse("$80,000–$120,000"),
          raw="$80,000–$120,000")
    rows = top_matches(store, limit=10, min_fit=0)
    assert len(rows) == 1
    r = rows[0]
    assert r.comp_min == 80000
    assert r.comp_max == 120000
    assert r.comp_currency == "USD"
    assert r.comp_period == "year"


def test_top_matches_handles_no_parsed_comp(tmp_path):
    store = _store(tmp_path)
    _seed(store, key="1", fit=80, parsed=None, raw="See website")
    r = top_matches(store, limit=10, min_fit=0)[0]
    assert r.comp_min is None
    assert r.comp_max is None
    assert r.comp_currency is None
    assert r.comp_period is None
    assert r.compensation == "See website"


def test_comp_display_prefers_parsed(tmp_path):
    store = _store(tmp_path)
    _seed(store, key="1", fit=80, parsed=parse("$80,000–$120,000"),
          raw="$80,000–$120,000")
    r = top_matches(store, limit=10, min_fit=0)[0]
    # ISO currency code wins (USD), formatted as k-shorthand, with /year period.
    assert "USD" in r.comp_display
    assert "80k" in r.comp_display
    assert "120k" in r.comp_display
    assert "/year" in r.comp_display


def test_comp_display_falls_back_to_raw(tmp_path):
    store = _store(tmp_path)
    _seed(store, key="1", fit=80, parsed=None, raw="Competitive")
    r = top_matches(store, limit=10, min_fit=0)[0]
    assert r.comp_display == "Competitive"


def test_comp_display_shows_em_dash_when_no_comp(tmp_path):
    store = _store(tmp_path)
    _seed(store, key="1", fit=80, parsed=None, raw=None)
    r = top_matches(store, limit=10, min_fit=0)[0]
    assert r.comp_display == "—"


def test_comp_display_hourly_format(tmp_path):
    store = _store(tmp_path)
    _seed(store, key="1", fit=80, parsed=parse("€60-80/hr"), raw="€60-80/hr")
    r = top_matches(store, limit=10, min_fit=0)[0]
    assert "EUR" in r.comp_display
    assert "/hour" in r.comp_display
    assert "60" in r.comp_display
    assert "80" in r.comp_display


def test_comp_display_single_value(tmp_path):
    store = _store(tmp_path)
    _seed(store, key="1", fit=80, parsed=parse("$90k"), raw="$90k")
    r = top_matches(store, limit=10, min_fit=0)[0]
    # Single value: only one amount, no dash separator
    assert "90k" in r.comp_display
    assert "–" not in r.comp_display  # en-dash absent for single values
