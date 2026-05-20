"""Trend scraper tests — respx-mocked HN, dev.to, Tavily."""
from __future__ import annotations

import httpx
import pytest
import respx

from career_os.db import Store
from career_os.profile import DEFAULT_PROFILE
from career_os.trends.sources import (
    DEVTO_TOP_URL,
    HN_FRONTPAGE_URL,
    TAVILY_SEARCH_URL,
    scan_devto,
    scan_hn,
    scan_sources,
    scan_tavily,
)


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'src.db'}")


# ---- HN ------------------------------------------------------------------

HN_PAYLOAD = {
    "hits": [
        {
            "objectID": "111",
            "title": "Anthropic releases tool streaming API",
            "url": "https://www.anthropic.com/news/streaming",
            "points": 420, "num_comments": 187,
            "created_at": "2026-05-19T10:00:00Z",
            "author": "swyx", "_tags": ["story", "front_page"],
        },
        {
            "objectID": "112",
            "title": "Show HN: I built a Laravel + Claude RAG",
            "url": "https://github.com/example/laravel-rag",
            "points": 95, "num_comments": 28,
            "created_at": "2026-05-19T08:00:00Z",
            "author": "akbak", "_tags": ["story", "front_page", "show_hn"],
        },
    ]
}


@pytest.mark.asyncio
@respx.mock
async def test_scan_hn_upserts_each_hit(store):
    respx.get(HN_FRONTPAGE_URL).mock(
        return_value=httpx.Response(200, json=HN_PAYLOAD)
    )
    async with httpx.AsyncClient() as client:
        n = await scan_hn(client, store, DEFAULT_PROFILE)
    assert n == 2
    from career_os.trends import list_trends
    rows = list_trends(store, min_signal=0.0)
    assert {t.external_id for t in rows} == {"111", "112"}
    # The Anthropic story should have higher signal than the Show HN
    by_id = {t.external_id: t for t in rows}
    assert by_id["111"].signal_score > by_id["112"].signal_score


@pytest.mark.asyncio
@respx.mock
async def test_scan_hn_skips_malformed_hits(store):
    bad_payload = {"hits": [
        {"objectID": "1", "title": "ok", "url": "https://a", "points": 5,
         "num_comments": 0, "created_at": "2026-05-19T10:00:00Z"},
        {"objectID": "", "title": "missing-id", "url": "https://b"},
        {"title": "no objectID", "url": "https://c"},
    ]}
    respx.get(HN_FRONTPAGE_URL).mock(
        return_value=httpx.Response(200, json=bad_payload)
    )
    async with httpx.AsyncClient() as client:
        n = await scan_hn(client, store, None)
    assert n == 1


# ---- dev.to --------------------------------------------------------------

DEVTO_PAYLOAD = [
    {
        "id": 7001,
        "title": "Building agents with Claude SDK",
        "url": "https://dev.to/akbak/agents-with-claude",
        "description": "How to wire Claude into your Laravel app",
        "positive_reactions_count": 250,
        "comments_count": 18,
        "tag_list": ["claude", "ai", "laravel"],
        "published_at": "2026-05-15T09:00:00Z",
        "user": {"username": "akbak"},
        "cover_image": "https://example.com/cover.jpg",
        "reading_time_minutes": 6,
    },
    {
        "id": 7002,
        "title": "PHP 8.4 release notes",
        "url": "https://dev.to/php/8-4",
        "positive_reactions_count": 80, "comments_count": 5,
        "tag_list": ["php"], "published_at": "2026-05-18T11:00:00Z",
        "description": "What's new",
    },
]


@pytest.mark.asyncio
@respx.mock
async def test_scan_devto_parses_articles(store):
    respx.get(DEVTO_TOP_URL).mock(
        return_value=httpx.Response(200, json=DEVTO_PAYLOAD)
    )
    async with httpx.AsyncClient() as client:
        n = await scan_devto(client, store, DEFAULT_PROFILE)
    assert n == 2
    from career_os.trends import list_trends
    rows = list_trends(store, min_signal=0.0)
    assert {t.external_id for t in rows} == {"7001", "7002"}
    by_id = {t.external_id: t for t in rows}
    assert "laravel" in by_id["7001"].tags
    assert by_id["7001"].summary is not None


# ---- Tavily --------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_scan_tavily_skipped_when_no_api_key(store, monkeypatch):
    from career_os.config import Settings

    def _no_key():
        return Settings(
            anthropic_api_key=None, database_url="sqlite:///x",
            smtp_provider=None, smtp_api_key=None,
            smtp_from="x", smtp_to="x", tavily_api_key=None,
        )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: _no_key()))
    async with httpx.AsyncClient() as client:
        n = await scan_tavily(client, store, None)
    assert n == 0


@pytest.mark.asyncio
@respx.mock
async def test_scan_tavily_upserts_results(store, monkeypatch):
    from career_os.config import Settings

    def _key():
        return Settings(
            anthropic_api_key=None, database_url="sqlite:///x",
            smtp_provider=None, smtp_api_key=None,
            smtp_from="x", smtp_to="x", tavily_api_key="test-tavily-key",
        )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: _key()))

    respx.post(TAVILY_SEARCH_URL).mock(return_value=httpx.Response(
        200, json={"results": [
            {"title": "Claude 4.6 released", "url": "https://anthropic.com/claude-4-6",
             "content": "Sonnet 4.6 improves coding...", "score": 0.95},
            {"title": "OpenAI's new model", "url": "https://openai.com/gpt-5",
             "content": "GPT-5 announced...", "score": 0.80},
        ]}
    ))
    async with httpx.AsyncClient() as client:
        n = await scan_tavily(client, store, None)
    # Without a profile we run only the two base queries; each returns 2 hits.
    assert n == 4  # 2 queries × 2 hits


# ---- orchestrator --------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_scan_sources_runs_each_and_swallows_failures(store):
    # HN succeeds; devto returns 503; Tavily skipped (no key by default).
    respx.get(HN_FRONTPAGE_URL).mock(
        return_value=httpx.Response(200, json=HN_PAYLOAD)
    )
    respx.get(DEVTO_TOP_URL).mock(return_value=httpx.Response(503))
    results = await scan_sources(store, DEFAULT_PROFILE)
    assert results["hn"] == 2
    assert results["devto"] == 0  # failure → 0, not exception


@pytest.mark.asyncio
@respx.mock
async def test_scan_sources_respects_source_filter(store):
    respx.get(HN_FRONTPAGE_URL).mock(
        return_value=httpx.Response(200, json=HN_PAYLOAD)
    )
    # devto endpoint MUST NOT be called when filtered out.
    results = await scan_sources(store, DEFAULT_PROFILE, sources=["hn"])
    assert "hn" in results
    assert "devto" not in results
