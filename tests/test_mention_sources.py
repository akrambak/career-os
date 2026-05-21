"""Mention scrapers — respx-mocked HN, dev.to, GitHub."""
from __future__ import annotations

import httpx
import pytest
import respx

from career_os.db import Store
from career_os.mentions.sources import (
    DEVTO_SEARCH_URL,
    HN_SEARCH_URL,
    scan_devto,
    scan_github,
    scan_hn,
    scan_sources,
)


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 's.db'}")


# ---- HN ------------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_scan_hn_upserts_comment_match(store):
    # Algolia returns a comment whose body contains our term.
    respx.get(HN_SEARCH_URL).mock(return_value=httpx.Response(200, json={
        "hits": [
            {
                "objectID": "11111",
                "comment_text": "I've been using bak-dev.com for a while — solid.",
                "author": "anon", "created_at_i": 1716200000,
            }
        ]
    }))
    async with httpx.AsyncClient() as client:
        n = await scan_hn(client, store, ["bak-dev.com"])
    assert n == 1
    from career_os.mentions import list_mentions
    rows = list_mentions(store)
    assert rows[0].source == "hn"
    assert rows[0].has_link is True  # bak-dev.com substring present


@pytest.mark.asyncio
@respx.mock
async def test_scan_hn_skips_hits_where_term_absent(store):
    respx.get(HN_SEARCH_URL).mock(return_value=httpx.Response(200, json={
        "hits": [
            {
                "objectID": "22222",
                "comment_text": "Nothing about us here.",
            }
        ]
    }))
    async with httpx.AsyncClient() as client:
        n = await scan_hn(client, store, ["bak-dev.com"])
    assert n == 0


@pytest.mark.asyncio
@respx.mock
async def test_scan_hn_handles_brand_name_unlinked(store):
    respx.get(HN_SEARCH_URL).mock(return_value=httpx.Response(200, json={
        "hits": [
            {
                "objectID": "33333",
                "comment_text": "AkBak's article was a good read.",
            }
        ]
    }))
    async with httpx.AsyncClient() as client:
        await scan_hn(client, store, ["AkBak"])
    from career_os.mentions import list_mentions
    rows = list_mentions(store)
    assert len(rows) == 1
    assert rows[0].has_link is False  # brand mention with no URL


# ---- dev.to --------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_scan_devto_filters_client_side(store):
    respx.get(DEVTO_SEARCH_URL).mock(return_value=httpx.Response(200, json=[
        {
            "id": 1, "title": "Building agents on bak-dev.com",
            "description": "A walkthrough", "url": "https://dev.to/x/1",
        },
        {
            "id": 2, "title": "Unrelated post",
            "description": "Nothing here", "url": "https://dev.to/x/2",
        },
    ]))
    async with httpx.AsyncClient() as client:
        n = await scan_devto(client, store, ["bak-dev.com"])
    assert n == 1


# ---- GitHub --------------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_scan_github_skips_without_token(store, monkeypatch):
    from career_os.config import Settings

    def _no_token():
        return Settings(
            anthropic_api_key=None, database_url="sqlite:///x",
            smtp_provider=None, smtp_api_key=None,
            smtp_from="x", smtp_to="x", tavily_api_key=None,
            github_token=None,
        )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: _no_token()))
    async with httpx.AsyncClient() as client:
        n = await scan_github(client, store, ["bak-dev.com"])
    assert n == 0


@pytest.mark.asyncio
@respx.mock
async def test_scan_github_upserts_with_token(store, monkeypatch):
    from career_os.config import Settings

    def _with_token():
        return Settings(
            anthropic_api_key=None, database_url="sqlite:///x",
            smtp_provider=None, smtp_api_key=None,
            smtp_from="x", smtp_to="x", tavily_api_key=None,
            github_token="gh-token",
        )
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls: _with_token()))
    respx.get("https://api.github.com/search/code").mock(
        return_value=httpx.Response(200, json={"items": [
            {
                "name": "README.md", "html_url": "https://github.com/u/r/blob/m/README.md",
                "repository": {"full_name": "u/r"},
            }
        ]})
    )
    async with httpx.AsyncClient() as client:
        n = await scan_github(client, store, ["akrambak/career-os"])
    assert n == 1


# ---- orchestrator --------------------------------------------------------

@pytest.mark.asyncio
@respx.mock
async def test_scan_sources_runs_each_and_swallows_failures(store):
    respx.get(HN_SEARCH_URL).mock(return_value=httpx.Response(200, json={
        "hits": [
            {"objectID": "1",
             "comment_text": "I love bak-dev.com"},
        ]
    }))
    respx.get(DEVTO_SEARCH_URL).mock(return_value=httpx.Response(503))
    # GitHub will skip (no token in default env from test runner)
    results = await scan_sources(store, terms=["bak-dev.com"])
    assert results["hn"] == 1
    assert results["devto"] == 0  # 503 → swallowed → 0


@pytest.mark.asyncio
@respx.mock
async def test_scan_sources_respects_source_filter(store):
    respx.get(HN_SEARCH_URL).mock(return_value=httpx.Response(200, json={
        "hits": [{"objectID": "1", "comment_text": "bak-dev.com mention"}]
    }))
    results = await scan_sources(store, sources=["hn"], terms=["bak-dev.com"])
    assert "hn" in results
    assert "devto" not in results
