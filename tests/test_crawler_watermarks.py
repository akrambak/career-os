"""Crawler integration: watermarks flush on success, --full-refresh bypass,
source-health surfacing of unchanged/failed."""
from __future__ import annotations

import httpx
import pytest
import respx

from career_os.crawler import crawl
from career_os.dashboard.queries import source_health
from career_os.db import Store
from career_os.scrapers.remoteok import RemoteOKScraper


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'c.db'}")


def _ro_payload(*ids):
    return [
        {"legal": "RemoteOK API"},
        *[
            {
                "id": str(i), "position": f"Job {i}", "company": "Acme",
                "url": f"https://remoteok.com/job/{i}",
                "description": "d", "tags": [], "location": "Remote",
                "date": "2026-05-19T10:00:00Z",
            } for i in ids
        ],
    ]


@pytest.mark.asyncio
@respx.mock
async def test_crawl_writes_top_level_watermark_on_success(store):
    respx.get(RemoteOKScraper.url).mock(
        return_value=httpx.Response(200, json=_ro_payload(3, 2, 1))
    )
    # Stub out the four other scrapers so crawl doesn't hit them.
    respx.get(host="weworkremotely.com").mock(return_value=httpx.Response(304))
    respx.get(host="remotive.com").mock(return_value=httpx.Response(503))
    respx.get(host="hn.algolia.com").mock(return_value=httpx.Response(
        200, json={"hits": []},
    ))
    await crawl(store, scraper_keys=["remoteok"])
    wm = store.get_watermark("remoteok")
    assert wm is not None
    assert wm.last_status == "ok"
    assert wm.last_external_id == "3"


@pytest.mark.asyncio
@respx.mock
async def test_full_refresh_ignores_prior_watermark(store):
    # Seed a prior watermark that would normally skip everything.
    store.save_watermark(
        source="remoteok", last_fetched_at="2026-05-19T10:00:00+00:00",
        last_status="ok", last_external_id="3",
    )
    respx.get(RemoteOKScraper.url).mock(
        return_value=httpx.Response(200, json=_ro_payload(3, 2, 1))
    )
    # full-refresh: every job is "new" from the watermark's POV
    results = await crawl(store, scraper_keys=["remoteok"], use_watermarks=False)
    assert results["remoteok"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_normal_crawl_respects_prior_watermark(store):
    store.save_watermark(
        source="remoteok", last_fetched_at="2026-05-19T10:00:00+00:00",
        last_status="ok", last_external_id="3",
    )
    respx.get(RemoteOKScraper.url).mock(
        return_value=httpx.Response(200, json=_ro_payload(3, 2, 1))
    )
    results = await crawl(store, scraper_keys=["remoteok"])
    # We've already seen id=3, so id=3 is the immediate stop. 0 new yielded.
    assert results["remoteok"] == 0
    wm = store.get_watermark("remoteok")
    assert wm.last_status == "unchanged"


@pytest.mark.asyncio
@respx.mock
async def test_source_health_surfaces_unchanged_status(store):
    respx.get(RemoteOKScraper.url).mock(
        return_value=httpx.Response(200, json=_ro_payload(3, 2, 1))
    )
    # First run: ingest 3.
    await crawl(store, scraper_keys=["remoteok"])
    # Second run: same payload → should record unchanged.
    await crawl(store, scraper_keys=["remoteok"])
    rows = source_health(store)
    by_source = {r.source: r for r in rows}
    assert by_source["remoteok"].last_status == "unchanged"
    assert by_source["remoteok"].status_display == "unchanged (304)"


@pytest.mark.asyncio
@respx.mock
async def test_source_health_includes_watermark_only_sources(store):
    """A scraper that's never ingested a job but has a watermark row should
    still appear in source_health (so failing-from-day-1 sources are visible)."""
    store.save_watermark(
        source="zombie", last_fetched_at="2026-05-19T10:00:00+00:00",
        last_status="failed", notes="HTTPError",
    )
    rows = source_health(store)
    by_source = {r.source: r for r in rows}
    assert "zombie" in by_source
    assert by_source["zombie"].last_status == "failed"
    assert by_source["zombie"].total == 0
