---
name: add-scraper
description: Add a new job/freelance-board scraper to Career-OS. Use when the user wants to add a source (Wellfound, EU freelance boards, RemoteHub, etc.) or when they say "scrape <site>". Walks the Scraper subclass + registry wiring + respx-mocked test recipe.
---

# Add a new scraper

A scraper is one Python file under `src/career_os/scrapers/`. It subclasses
`Scraper`, sets a unique `key`, implements an async `fetch()` that yields
`JobPost`, and gets registered in `scrapers/registry.py`. CI runs the test
suite on every push, so add a respx-mocked fixture test alongside.

## Files you will touch

| Path | Why |
|---|---|
| `src/career_os/scrapers/<key>.py` | new scraper module |
| `src/career_os/scrapers/registry.py` | import + add to `REGISTRY` tuple |
| `tests/test_<key>_scraper.py` | respx-mocked round-trip test |

Nothing else needs to change. The `career-os fetch` CLI auto-discovers
through `REGISTRY`, and the dashboard's source-health table indexes by the
`source` column populated from `JobPost.source = scraper.key`.

## Step 1 — Investigate the source first

Before writing code, confirm:

1. **Endpoint shape.** `curl -sI <url>` to check status + content-type. Does
   it serve JSON, RSS, HTML?  Note rate limits + any auth requirements.
2. **Stable IDs.** Pick a field for `external_id` that never changes for a
   given posting. If the source rotates IDs (some boards reissue weekly), use
   a hash of `(url, title)` instead.
3. **Channel signal.** What field indicates FT vs freelance? If the source
   mixes them (Remotive does — `job_type` field), branch on it; if it's
   single-purpose (HN "Seeking freelancer?" is all freelance), hardcode.
4. **Tags.** Lowercase them. Tags are used by the scorer and the keyword
   stub, so quality matters.

If you have to negotiate the endpoint live, you can do a one-off `curl` from
this session before coding. Don't add a new dependency to fetch — `httpx` is
already in `pyproject.toml`.

## Step 2 — Pattern to follow

The interface is in `src/career_os/scrapers/base.py:11`. Two existing scrapers
show the canonical shapes:

- **JSON API** → `scrapers/remoteok.py` (single `GET`, iterate items)
- **JSON API with multiple categories** → `scrapers/remotive.py` (one request
  per category, swallows per-category HTTP errors so a bad category doesn't
  kill the whole source)
- **RSS** → `scrapers/weworkremotely.py`
- **Algolia search** (HN-style) → `scrapers/hn_freelancer.py` (paginated,
  structured-field extraction from comment text)

Match the shape closest to the new source — don't invent a new pattern.

Skeleton for a JSON source:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from ..models import Channel, JobPost
from .base import Scraper


class <Name>Scraper(Scraper):
    """<one-line description>."""

    key = "<short-stable-key>"  # matches CLI `--source <key>` and `JobPost.source`
    url = "<endpoint>"

    async def fetch(self, client: httpx.AsyncClient) -> AsyncIterator[JobPost]:
        try:
            r = await client.get(
                self.url, headers=self._client_headers(), timeout=30.0,
            )
            r.raise_for_status()
        except httpx.HTTPError:
            return
        for item in r.json().get("jobs", []):
            job = self._parse(item)
            if job:
                yield job

    def _parse(self, item: dict) -> JobPost | None:
        external_id = str(item.get("id") or "").strip()
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not external_id or not url or not title:
            return None
        # Channel detection — branch on whatever field signals contract/FT.
        channel = Channel.FREELANCE if "..." else Channel.FT
        return JobPost(
            source=self.key,
            external_id=external_id,
            url=url,
            title=title,
            company=item.get("company") or None,
            location=item.get("location") or "Remote",
            description=item.get("description", ""),
            tags=[t.lower() for t in item.get("tags", []) if isinstance(t, str)],
            channel=channel,
            compensation=item.get("salary") or None,
            posted_at=_parse_iso(item.get("posted_at")),
        )


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
```

### Hard rules

- **Yield, don't collect.** `fetch` is an `AsyncIterator`. The crawler upserts
  each job as it arrives so the SQLite write barrier is amortized. Don't
  build a list then yield from it.
- **Swallow per-item errors.** A malformed entry must not abort the source.
  Wrap `_parse` in try/except or return `None` and skip. See `remoteok.py:21`.
- **HTML stripping.** If `description` contains HTML, strip it with the same
  two-regex pattern as `remotive.py:47` (don't pull in BeautifulSoup).
- **User-Agent.** Inherit `_client_headers()` from the base. Don't override
  unless the source blocks the default UA — add a comment explaining why if
  you do.
- **Timeouts.** Always set `timeout=30.0`. The crawler runs sources
  concurrently; one slow source must not stall the rest.

## Step 3 — Register it

Edit `src/career_os/scrapers/registry.py`:

```python
from .<your_file> import <Your>Scraper

REGISTRY: dict[str, type[Scraper]] = {
    cls.key: cls
    for cls in (
        # ...existing classes,
        <Your>Scraper,
    )
}
```

That's the only registration step. Verify with:

```bash
.venv/bin/career-os sources
```

Your key should appear.

## Step 4 — Write a test

Tests live under `tests/`. Use `respx` (already in `[dev]`) to mock the HTTP
call so the test is hermetic. Pattern:

```python
import httpx
import pytest
import respx

from career_os.scrapers.<your_file> import <Your>Scraper


@pytest.mark.asyncio
@respx.mock
async def test_<key>_parses_a_well_formed_item():
    respx.get(<Your>Scraper.url).mock(
        return_value=httpx.Response(200, json={"jobs": [{
            "id": "abc",
            "url": "https://example.com/abc",
            "title": "Senior Laravel Engineer",
            "company": "Acme",
            "description": "<p>Build stuff</p>",
            "tags": ["Laravel", "Vue"],
        }]})
    )
    scraper = <Your>Scraper()
    async with httpx.AsyncClient() as client:
        jobs = [j async for j in scraper.fetch(client)]
    assert len(jobs) == 1
    j = jobs[0]
    assert j.source == "<key>"
    assert j.external_id == "abc"
    assert "laravel" in j.tags  # lowercased
```

Also add a fixture for **missing required fields** (id, url, title) — the
scraper must silently drop that item, not raise. And one for **HTTP 500** —
`fetch` returns nothing, no exception escapes.

## Step 5 — Smoke-test live

Once tests pass, run it for real once:

```bash
.venv/bin/career-os fetch --source <key>
.venv/bin/career-os sources    # confirm the row count went up
```

If the source returns 0 jobs the first time, something is wrong with parsing
— don't ship and assume "no postings today."

## Step 6 — Commit

One commit per scraper. Message shape (match recent history):

```
Add <Name> scraper (<key>) — <one-line about what it covers>
```

Don't bundle scrapers with unrelated changes — they're small enough to land
independently and the rollback story stays clean.

## Anti-patterns

- **Don't add an `__init__` to the scraper** unless it needs configuration.
  All existing scrapers are stateless; the crawler instantiates them with
  zero args (`registry.py:25`).
- **Don't read environment variables inside the scraper.** Config flows
  through `Settings.load()` at the CLI layer. If a source needs an API key,
  ask before adding it — the project is built around free/public sources on
  purpose.
- **Don't add retries inside `fetch`.** The crawler already swallows
  per-source failures (`crawler/run.py:21`). Multiple retry layers make
  failure modes harder to read in CI logs.
- **Don't infer channel from title keywords.** Use a structured source field.
  Title heuristics produce false positives that pollute the funnel.
