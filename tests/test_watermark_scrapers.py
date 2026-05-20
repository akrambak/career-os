"""Per-scraper watermark behaviour (Tier 2, Upgrade 6).

We exercise each scraper through its `fetch` async iterator with a
respx-mocked HTTP layer and verify:
  1. Prior watermark state controls the request (If-None-Match, cursor stops).
  2. The scraper stages new watermark records via WatermarkCtx.
"""
from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from career_os.scrapers.hn_freelancer import HNFreelancerScraper
from career_os.scrapers.hn_whoishiring import HNWhoIsHiringScraper
from career_os.scrapers.remoteok import RemoteOKScraper
from career_os.scrapers.remotive import RemotiveScraper
from career_os.scrapers.weworkremotely import WeWorkRemotelyScraper
from career_os.watermark import Watermark, WatermarkCtx


def _wm(source: str, **fields) -> Watermark:
    return Watermark(
        source=source, last_fetched_at=datetime.now(UTC), last_status="ok", **fields,
    )


def _ctx_with(prior: dict[str, Watermark]) -> WatermarkCtx:
    return WatermarkCtx(getter=lambda k: prior.get(k))


# ---- WeWorkRemotely: 304 + ETag -----------------------------------------

WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]

RSS_OK_BODY = b"""<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Acme: Senior Engineer</title>
    <link>https://weworkremotely.com/remote-jobs/acme-1</link>
    <description>Build stuff.</description>
    <pubDate>Mon, 19 May 2026 10:00:00 +0000</pubDate>
  </item>
</channel></rss>"""


@pytest.mark.asyncio
@respx.mock
async def test_wwr_sends_if_none_match_when_prior_etag():
    prior = {
        "weworkremotely:programming": _wm(
            "weworkremotely:programming", etag='W/"abc"',
            last_modified="Mon, 19 May 2026 09:00:00 GMT",
        ),
    }
    ctx = _ctx_with(prior)
    captured: dict[str, dict] = {}
    def _handler(request):
        captured[str(request.url)] = dict(request.headers)
        return httpx.Response(304)
    respx.get(WWR_FEEDS[0]).mock(side_effect=_handler)
    respx.get(WWR_FEEDS[1]).mock(return_value=httpx.Response(304))

    scraper = WeWorkRemotelyScraper()
    async with httpx.AsyncClient() as client:
        results = [j async for j in scraper.fetch(client, ctx)]
    assert results == []
    # First feed got the conditional headers.
    headers = captured[WWR_FEEDS[0]]
    assert headers["if-none-match"] == 'W/"abc"'
    assert headers["if-modified-since"] == "Mon, 19 May 2026 09:00:00 GMT"
    # Both sub-feeds recorded as unchanged.
    assert ctx.records["weworkremotely:programming"]["last_status"] == "unchanged"
    assert ctx.records["weworkremotely:fullstack"]["last_status"] == "unchanged"


@pytest.mark.asyncio
@respx.mock
async def test_wwr_200_records_new_etag_and_yields_jobs():
    respx.get(WWR_FEEDS[0]).mock(
        return_value=httpx.Response(
            200, content=RSS_OK_BODY,
            headers={
                "ETag": 'W/"xyz"',
                "Last-Modified": "Mon, 19 May 2026 12:00:00 GMT",
            },
        )
    )
    respx.get(WWR_FEEDS[1]).mock(return_value=httpx.Response(304))

    ctx = _ctx_with({})
    scraper = WeWorkRemotelyScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, ctx)]
    assert len(jobs) == 1
    rec = ctx.records["weworkremotely:programming"]
    assert rec["last_status"] == "ok"
    assert rec["etag"] == 'W/"xyz"'
    assert rec["last_modified"] == "Mon, 19 May 2026 12:00:00 GMT"


@pytest.mark.asyncio
@respx.mock
async def test_wwr_no_watermark_ctx_still_works():
    """Back-compat: passing watermarks=None must not crash and must yield."""
    respx.get(WWR_FEEDS[0]).mock(
        return_value=httpx.Response(200, content=RSS_OK_BODY)
    )
    respx.get(WWR_FEEDS[1]).mock(return_value=httpx.Response(200, content=RSS_OK_BODY))
    scraper = WeWorkRemotelyScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, None)]
    assert len(jobs) == 1  # dedup by external_id across the two feeds


# ---- RemoteOK: stop on known external_id --------------------------------

def _ro_payload(*ids: int) -> list[dict]:
    legal = {"legal": "RemoteOK API"}
    items = [
        {
            "id": str(i), "position": f"Job {i}", "company": "Acme",
            "url": f"https://remoteok.com/job/{i}",
            "description": "d", "tags": [], "location": "Remote",
            "date": "2026-05-19T10:00:00Z",
        } for i in ids
    ]
    return [legal, *items]


@pytest.mark.asyncio
@respx.mock
async def test_remoteok_stops_at_prior_external_id():
    # Payload is newest-first: 5, 4, 3, 2, 1. Prior watermark said we last
    # saw "3" — we should yield 5, 4 then stop.
    respx.get(RemoteOKScraper.url).mock(
        return_value=httpx.Response(200, json=_ro_payload(5, 4, 3, 2, 1))
    )
    ctx = _ctx_with({"remoteok": _wm("remoteok", last_external_id="3")})
    scraper = RemoteOKScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, ctx)]
    assert [j.external_id for j in jobs] == ["5", "4"]
    rec = ctx.records["remoteok"]
    assert rec["last_external_id"] == "5"  # new high-water mark
    assert rec["last_status"] == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_remoteok_no_new_jobs_records_unchanged():
    """When the very first item matches the prior id, nothing is yielded."""
    respx.get(RemoteOKScraper.url).mock(
        return_value=httpx.Response(200, json=_ro_payload(7, 6, 5))
    )
    ctx = _ctx_with({"remoteok": _wm("remoteok", last_external_id="7")})
    scraper = RemoteOKScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, ctx)]
    assert jobs == []
    assert ctx.records["remoteok"]["last_status"] == "unchanged"


@pytest.mark.asyncio
@respx.mock
async def test_remoteok_first_run_records_max_id():
    """No prior watermark → yield everything, record max id."""
    respx.get(RemoteOKScraper.url).mock(
        return_value=httpx.Response(200, json=_ro_payload(5, 4, 3))
    )
    ctx = _ctx_with({})
    scraper = RemoteOKScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, ctx)]
    assert {j.external_id for j in jobs} == {"5", "4", "3"}
    assert ctx.records["remoteok"]["last_external_id"] == "5"


# ---- Remotive: per-category cursor --------------------------------------

REMOTIVE_URL = RemotiveScraper.url


def _rv_payload(*ids: int) -> dict:
    return {
        "jobs": [
            {
                "id": i, "title": f"Job {i}", "url": f"https://remotive.com/r/{i}",
                "company_name": "Acme", "candidate_required_location": "Worldwide",
                "description": "d", "tags": [],
                "job_type": "full_time", "publication_date": "2026-05-19T10:00:00",
                "salary": "",
            } for i in ids
        ]
    }


@pytest.mark.asyncio
@respx.mock
async def test_remotive_stops_at_prior_id():
    # Per category. Default scraper categories = ("software-dev",).
    respx.get(REMOTIVE_URL).mock(
        return_value=httpx.Response(200, json=_rv_payload(50, 49, 48, 47))
    )
    ctx = _ctx_with({
        "remotive:software-dev": _wm("remotive:software-dev", last_external_id="48"),
    })
    scraper = RemotiveScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, ctx)]
    assert [j.external_id for j in jobs] == ["50", "49"]
    sub = ctx.records["remotive:software-dev"]
    assert sub["last_external_id"] == "50"
    assert sub["last_status"] == "ok"
    # Top-level row also recorded
    assert ctx.records["remotive"]["last_status"] == "ok"
    assert ctx.records["remotive"]["last_external_id"] == "50"


@pytest.mark.asyncio
@respx.mock
async def test_remotive_failed_request_records_failed():
    respx.get(REMOTIVE_URL).mock(return_value=httpx.Response(503))
    ctx = _ctx_with({})
    scraper = RemotiveScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, ctx)]
    assert jobs == []
    assert ctx.records["remotive:software-dev"]["last_status"] == "failed"
    assert ctx.records["remotive"]["last_status"] == "failed"


# ---- HN scrapers: created_at_i cursor -----------------------------------

HN_SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
HN_ITEM = "https://hn.algolia.com/api/v1/items/{}"


@pytest.mark.asyncio
@respx.mock
async def test_hn_freelancer_filters_by_cursor():
    respx.get(HN_SEARCH).mock(return_value=httpx.Response(200, json={
        "hits": [{"objectID": "999", "title": "Freelancer? Seeking freelancer?"}],
    }))
    children = [
        # Old comments — already-seen — cursor=1700000200 means we want >.
        {"id": 10, "text": "SEEKING FREELANCER\nOld one", "author": "a",
         "created_at_i": 1700000100, "created_at": "2026-04-01T00:00:00Z"},
        # New comments — must be yielded.
        {"id": 11, "text": "SEEKING FREELANCER\nNew one", "author": "b",
         "created_at_i": 1700000300, "created_at": "2026-05-01T00:00:00Z"},
        {"id": 12, "text": "SEEKING FREELANCER\nNewer", "author": "c",
         "created_at_i": 1700000400, "created_at": "2026-05-02T00:00:00Z"},
    ]
    respx.get(HN_ITEM.format(999)).mock(return_value=httpx.Response(
        200, json={"children": children, "id": 999},
    ))

    ctx = _ctx_with({
        "hn_freelancer:999": _wm("hn_freelancer:999", last_cursor="1700000200"),
    })
    scraper = HNFreelancerScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, ctx)]
    assert [j.external_id for j in jobs] == ["11", "12"]
    rec = ctx.records["hn_freelancer:999"]
    assert rec["last_cursor"] == "1700000400"
    assert rec["last_status"] == "ok"


@pytest.mark.asyncio
@respx.mock
async def test_hn_freelancer_no_new_records_unchanged():
    respx.get(HN_SEARCH).mock(return_value=httpx.Response(200, json={
        "hits": [{"objectID": "999", "title": "Freelancer? Seeking freelancer?"}],
    }))
    children = [
        {"id": 10, "text": "SEEKING FREELANCER\nOld", "author": "a",
         "created_at_i": 1700000100, "created_at": "2026-04-01T00:00:00Z"},
    ]
    respx.get(HN_ITEM.format(999)).mock(return_value=httpx.Response(
        200, json={"children": children, "id": 999},
    ))
    ctx = _ctx_with({
        "hn_freelancer:999": _wm("hn_freelancer:999", last_cursor="1700000999"),
    })
    scraper = HNFreelancerScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, ctx)]
    assert jobs == []
    assert ctx.records["hn_freelancer:999"]["last_status"] == "unchanged"


@pytest.mark.asyncio
@respx.mock
async def test_hn_whoishiring_filters_by_cursor():
    respx.get(HN_SEARCH).mock(return_value=httpx.Response(200, json={
        "hits": [{"objectID": "888", "title": "Ask HN: Who is hiring? (May 2026)"}],
    }))
    children = [
        {"id": 21, "text": "Old | Co | Remote | hiring engineers (60+ chars padding here)",
         "created_at_i": 1700000100, "created_at": "2026-04-01T00:00:00Z"},
        {"id": 22, "text": "New | Co | Remote | hiring engineers (60+ chars padding here)",
         "created_at_i": 1700000300, "created_at": "2026-05-01T00:00:00Z"},
    ]
    respx.get(HN_ITEM.format(888)).mock(return_value=httpx.Response(
        200, json={"children": children, "id": 888},
    ))
    ctx = _ctx_with({
        "hn_whoishiring:888": _wm("hn_whoishiring:888", last_cursor="1700000200"),
    })
    scraper = HNWhoIsHiringScraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client, ctx)]
    assert [j.external_id for j in jobs] == ["22"]
    assert ctx.records["hn_whoishiring:888"]["last_cursor"] == "1700000300"
