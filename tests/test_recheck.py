"""Tier 3 Upgrade 8 — stale-job detection tests.

Coverage:
  - 404/410 → closed (reason='gone')
  - Redirected to /jobs/ → closed (reason='redirected-to-listings')
  - 200 healthy → kept, recheck_attempts cleared
  - 5xx → transient, recheck_attempts incremented
  - 3 strikes → closed (reason='unreachable')
  - Source-specific is_closed hook → closed (reason='source-marker')
  - Network exception (timeout) → transient + strike-bump
  - top_scored / top_matches exclude is_closed=1
  - Re-listing via fetch resets is_closed
  - Recheck candidates respect max_age_days + source filter
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from career_os.db import Store
from career_os.models import Channel, JobPost
from career_os.recheck import TRANSIENT_STRIKE_LIMIT, recheck, summarize
from career_os.scrapers.remoteok import RemoteOKScraper


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'rc.db'}")


def _seed(store: Store, *, key: str, url: str, source: str = "remoteok") -> str:
    job = JobPost(
        source=source, external_id=key,
        url=url, title=f"Job {key}", description="d",
        channel=Channel.FT,
    )
    store.upsert_job(job)
    return job.key


# ---- HTTP-status decisions -----------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_404_marks_closed_gone(store):
    _seed(store, key="1", url="https://r.com/dead")
    respx.get("https://r.com/dead").mock(return_value=httpx.Response(404))
    outcomes = await recheck(store)
    assert len(outcomes) == 1
    assert outcomes[0].decision == "closed"
    assert outcomes[0].reason == "gone"
    # Job persists in DB but is_closed=1; verify via raw query.
    with store._conn() as c:
        row = c.execute(
            "SELECT is_closed FROM jobs WHERE key = ?", ("remoteok:1",),
        ).fetchone()
    assert row["is_closed"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_410_marks_closed_gone(store):
    _seed(store, key="1", url="https://r.com/gone")
    respx.get("https://r.com/gone").mock(return_value=httpx.Response(410))
    outcomes = await recheck(store)
    assert outcomes[0].decision == "closed"
    assert outcomes[0].reason == "gone"


@pytest.mark.asyncio
@respx.mock
async def test_200_keeps_job_and_clears_attempts(store):
    _seed(store, key="1", url="https://r.com/live")
    respx.get("https://r.com/live").mock(return_value=httpx.Response(200, text="hi"))
    outcomes = await recheck(store)
    assert outcomes[0].decision == "kept"
    with store._conn() as c:
        row = c.execute(
            "SELECT is_closed, recheck_attempts, last_rechecked_at "
            "FROM jobs WHERE key = ?", ("remoteok:1",),
        ).fetchone()
    assert row["is_closed"] == 0
    assert row["recheck_attempts"] == 0
    assert row["last_rechecked_at"] is not None


@pytest.mark.asyncio
@respx.mock
async def test_5xx_bumps_recheck_attempts(store):
    _seed(store, key="1", url="https://r.com/flaky")
    respx.get("https://r.com/flaky").mock(return_value=httpx.Response(503))
    outcomes = await recheck(store)
    assert outcomes[0].decision == "transient"
    with store._conn() as c:
        row = c.execute(
            "SELECT is_closed, recheck_attempts FROM jobs WHERE key = ?",
            ("remoteok:1",),
        ).fetchone()
    assert row["is_closed"] == 0
    assert row["recheck_attempts"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_three_strikes_marks_closed_unreachable(store):
    _seed(store, key="1", url="https://r.com/strikes")
    respx.get("https://r.com/strikes").mock(return_value=httpx.Response(503))
    for _ in range(TRANSIENT_STRIKE_LIMIT):
        await recheck(store, max_age_days=-1)  # force selection regardless of time
    with store._conn() as c:
        row = c.execute(
            "SELECT is_closed FROM jobs WHERE key = ?", ("remoteok:1",),
        ).fetchone()
    assert row["is_closed"] == 1


# ---- Redirect to listings ------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_redirect_to_listings_marks_closed(store):
    _seed(store, key="1", url="https://r.com/job/abc")
    # respx supports follow_redirects=True — return a 301 then a 200 listings page.
    respx.get("https://r.com/job/abc").mock(return_value=httpx.Response(
        301, headers={"Location": "https://r.com/jobs/"},
    ))
    respx.get("https://r.com/jobs/").mock(
        return_value=httpx.Response(200, text="job listings")
    )
    outcomes = await recheck(store)
    assert outcomes[0].decision == "closed"
    assert outcomes[0].reason == "redirected-to-listings"


@pytest.mark.asyncio
@respx.mock
async def test_redirect_to_real_job_does_not_close(store):
    """A redirect to a real /job/<id>/ path is NOT a closure signal."""
    _seed(store, key="1", url="https://r.com/job/abc")
    respx.get("https://r.com/job/abc").mock(return_value=httpx.Response(
        301, headers={"Location": "https://r.com/job/xyz"},
    ))
    respx.get("https://r.com/job/xyz").mock(return_value=httpx.Response(200, text="hi"))
    outcomes = await recheck(store)
    assert outcomes[0].decision == "kept"


# ---- Source-specific marker ----------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_source_specific_marker_closes(store, monkeypatch):
    _seed(store, key="1", url="https://r.com/job/abc")
    respx.get("https://r.com/job/abc").mock(
        return_value=httpx.Response(200, text="this position is no longer available")
    )

    def is_closed_override(self, response):
        return "no longer available" in (response.text or "")
    monkeypatch.setattr(RemoteOKScraper, "is_closed", is_closed_override)
    outcomes = await recheck(store)
    assert outcomes[0].decision == "closed"
    assert outcomes[0].reason == "source-marker"


# ---- Transient (network) errors ------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_network_timeout_is_transient(store):
    _seed(store, key="1", url="https://r.com/timeout")
    respx.get("https://r.com/timeout").mock(side_effect=httpx.ConnectTimeout("slow"))
    outcomes = await recheck(store)
    assert outcomes[0].decision == "transient"


# ---- Candidate selection -------------------------------------------------

def test_recheck_candidates_respects_max_age_days(store):
    """Jobs rechecked recently aren't pulled again."""
    _seed(store, key="recent", url="https://r.com/1")
    _seed(store, key="stale", url="https://r.com/2")
    # Pretend 'recent' was rechecked yesterday; 'stale' a month ago.
    now = datetime.now(UTC)
    with store._conn() as c:
        c.execute(
            "UPDATE jobs SET last_rechecked_at = ? WHERE key = ?",
            ((now - timedelta(days=1)).isoformat(), "remoteok:recent"),
        )
        c.execute(
            "UPDATE jobs SET last_rechecked_at = ? WHERE key = ?",
            ((now - timedelta(days=30)).isoformat(), "remoteok:stale"),
        )
    candidates = store.recheck_candidates(max_age_days=7)
    keys = {j.key for j in candidates}
    assert "remoteok:stale" in keys
    assert "remoteok:recent" not in keys


def test_recheck_candidates_excludes_closed(store):
    _seed(store, key="1", url="https://r.com/dead")
    store.mark_closed("remoteok:1", reason="gone")
    assert store.recheck_candidates() == []


def test_recheck_candidates_source_filter(store):
    _seed(store, key="1", url="https://r.com/1", source="remoteok")
    _seed(store, key="2", url="https://rv.com/2", source="remotive")
    candidates = store.recheck_candidates(source="remoteok")
    assert [j.source for j in candidates] == ["remoteok"]


# ---- Closed jobs are hidden from top queries -----------------------------

def test_top_scored_excludes_closed(store):
    from career_os.models import Score
    key = _seed(store, key="1", url="https://r.com/dead")
    store.save_score(Score(
        job_key=key, fit=90, reasoning="strong", pros=["x"], cons=[],
    ))
    store.mark_closed(key, reason="gone")
    assert store.top_scored(limit=10, min_fit=0) == []


def test_top_matches_excludes_closed(store):
    from career_os.dashboard.queries import top_matches
    from career_os.models import Score
    key = _seed(store, key="1", url="https://r.com/dead")
    store.save_score(Score(
        job_key=key, fit=90, reasoning="strong", pros=["x"], cons=[],
    ))
    store.mark_closed(key, reason="gone")
    assert top_matches(store, limit=10, min_fit=0) == []


# ---- Re-listing resets is_closed ----------------------------------------

def test_upsert_clears_closed_flag(store):
    """If a source re-lists a job we previously marked closed, upsert
    should reset is_closed/closed_at/last_rechecked_at."""
    key = _seed(store, key="1", url="https://r.com/job/1")
    store.mark_closed(key, reason="gone")
    # Re-list: same JobPost.key, upsert path runs.
    relisted = JobPost(
        source="remoteok", external_id="1",
        url="https://r.com/job/1", title="Job 1 (re-listed)",
        description="d", channel=Channel.FT,
    )
    store.upsert_job(relisted)
    with store._conn() as c:
        row = c.execute(
            "SELECT is_closed, closed_at, last_rechecked_at, recheck_attempts "
            "FROM jobs WHERE key = ?", (key,),
        ).fetchone()
    assert row["is_closed"] == 0
    assert row["closed_at"] is None
    assert row["last_rechecked_at"] is None
    assert row["recheck_attempts"] == 0


# ---- summarize -----------------------------------------------------------

def test_summarize_buckets_outcomes():
    from career_os.recheck import RecheckOutcome
    outcomes = [
        RecheckOutcome("a", "kept", None, 200),
        RecheckOutcome("b", "closed", "gone", 404),
        RecheckOutcome("c", "closed", "redirected-to-listings", 200),
        RecheckOutcome("d", "transient", "http 503", 503),
    ]
    s = summarize(outcomes)
    assert s == {"kept": 1, "closed": 2, "transient": 1}
