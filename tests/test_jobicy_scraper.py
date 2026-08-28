from __future__ import annotations

import httpx
import pytest
import respx

from career_os.models import Channel
from career_os.scrapers.jobicy import JobicyScraper
from career_os.watermark import WatermarkCtx

FT_ITEM = {
    "id": 151780,
    "url": "https://jobicy.com/jobs/151780-senior-laravel-engineer",
    "jobTitle": "Senior Laravel Engineer",
    "companyName": "Acme",
    "jobGeo": "EMEA",
    "jobType": ["Full-Time"],
    "jobIndustry": ["Software Development", "E-Commerce"],
    "jobExcerpt": "Build stuff",
    "jobDescription": "<p>Build <strong>stuff</strong> with Laravel</p>",
    "pubDate": "2026-08-26T12:42:49+00:00",
    "salaryMin": 90000,
    "salaryMax": 120000,
    "salaryCurrency": "EUR",
    "salaryPeriod": "yearly",
}


def _ctx() -> tuple[WatermarkCtx, list]:
    staged: list = []
    ctx = WatermarkCtx(getter=lambda k: None)
    ctx.record = lambda source, **kw: staged.append((source, kw))  # type: ignore[method-assign]
    return ctx, staged


async def _run(scraper: JobicyScraper, watermarks=None):
    async with httpx.AsyncClient() as client:
        return [j async for j in scraper.fetch(client, watermarks)]


@pytest.mark.asyncio
@respx.mock
async def test_parses_well_formed_item():
    respx.get(JobicyScraper.url).mock(
        return_value=httpx.Response(200, json={"jobs": [FT_ITEM]})
    )
    jobs = await _run(JobicyScraper())
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source == "jobicy"
    assert j.external_id == "151780"
    assert j.channel is Channel.FT
    assert j.location == "EMEA"
    assert "software development" in j.tags  # lowercased
    assert "<" not in j.description and "Laravel" in j.description  # HTML stripped
    assert j.parsed_compensation is not None
    assert j.parsed_compensation.currency == "EUR"
    assert j.parsed_compensation.period == "year"
    assert j.parsed_compensation.min_amount == 90000


@pytest.mark.asyncio
@respx.mock
async def test_contract_type_maps_to_freelance():
    item = {**FT_ITEM, "id": 2, "jobType": ["Contract"]}
    respx.get(JobicyScraper.url).mock(
        return_value=httpx.Response(200, json={"jobs": [item]})
    )
    jobs = await _run(JobicyScraper())
    assert jobs[0].channel is Channel.FREELANCE


@pytest.mark.asyncio
@respx.mock
async def test_missing_required_fields_dropped():
    bad = [
        {**FT_ITEM, "id": None},
        {**FT_ITEM, "url": ""},
        {**FT_ITEM, "jobTitle": "  "},
    ]
    respx.get(JobicyScraper.url).mock(
        return_value=httpx.Response(200, json={"jobs": bad})
    )
    assert await _run(JobicyScraper()) == []


@pytest.mark.asyncio
@respx.mock
async def test_unmapped_period_keeps_amount_but_abstains_on_conversion():
    item = {**FT_ITEM, "id": 3, "salaryPeriod": "weekly"}
    respx.get(JobicyScraper.url).mock(
        return_value=httpx.Response(200, json={"jobs": [item]})
    )
    comp = (await _run(JobicyScraper()))[0].parsed_compensation
    # Keep the numeric range, but leave period unset so the floor filter abstains
    # rather than treating a weekly rate as annual.
    assert comp is not None and comp.min_amount == 90000
    assert comp.period is None
    assert comp.to_eur_hourly() is None


@pytest.mark.asyncio
@respx.mock
async def test_http_error_yields_nothing_and_records_failed():
    respx.get(JobicyScraper.url).mock(return_value=httpx.Response(500))
    ctx, staged = _ctx()
    assert await _run(JobicyScraper(), ctx) == []
    assert staged == [("jobicy", {"status": "failed"})]


@pytest.mark.asyncio
@respx.mock
async def test_records_watermark_with_max_id_on_success():
    items = [FT_ITEM, {**FT_ITEM, "id": 151999}]
    respx.get(JobicyScraper.url).mock(
        return_value=httpx.Response(200, json={"jobs": items})
    )
    ctx, staged = _ctx()
    await _run(JobicyScraper(), ctx)
    assert staged == [("jobicy", {"status": "ok", "last_external_id": "151999"})]
