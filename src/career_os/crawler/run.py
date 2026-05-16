from __future__ import annotations

import asyncio
import logging

import httpx

from ..db import Store
from ..scrapers import REGISTRY, Scraper

logger = logging.getLogger(__name__)


async def crawl(store: Store, scraper_keys: list[str] | None = None) -> dict[str, int]:
    """Run scrapers concurrently, upsert results, return per-source new-job counts."""
    keys = scraper_keys or list(REGISTRY)
    results: dict[str, int] = {}
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = {key: _run_one(REGISTRY[key](), client, store) for key in keys}
        for key, coro in tasks.items():
            try:
                results[key] = await coro
            except Exception as exc:  # noqa: BLE001 — bad source shouldn't kill the crawl
                logger.warning("scraper %s failed: %s", key, exc)
                results[key] = 0
    return results


async def _run_one(scraper: Scraper, client: httpx.AsyncClient, store: Store) -> int:
    new = 0
    async for job in scraper.fetch(client):
        if store.upsert_job(job):
            new += 1
    return new


def crawl_sync(store: Store, scraper_keys: list[str] | None = None) -> dict[str, int]:
    return asyncio.run(crawl(store, scraper_keys))
