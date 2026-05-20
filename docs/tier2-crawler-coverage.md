# Tier 2 — Crawler coverage

**Goal:** widen the funnel without lowering its signal. New source types
(browser-required, EU-specific) and stop re-pulling jobs we've already
seen. This tier only makes sense after [Tier 1](./tier1-crawler-quality.md)
ships — without dedup, floor filtering, and parsed salary, every new
source just multiplies noise.

**Non-goal:** anything that changes scorer prompts or pipeline stages.
Tier 3 (stale-job detection, watch lists, change-diff, multi-channel
funnel) is a separate stream.

---

## Success metrics

Measured by `career-os fetch` on a steady-state DB (Tier 1 already in
production for ≥ 1 week):

| Metric | Today | Target after Tier 2 |
|---|---|---|
| Distinct canonical sources sampled per fetch | 5 | 9–11 |
| Avg new-job yield per `fetch` run | re-pulls everything; "new" mostly == diff vs upserts | 5–50 truly new postings, rest 304s |
| Wall-time of a full `fetch` (warm DB) | ~30–60s (5 sources × full pull) | < 20s (most sources return 304 or short cursor delta) |
| Browser-scraped sources contributing > 0 jobs/day | 0 | ≥ 1 (Wellfound) on local runs, optional LinkedIn Jobs |
| EU-freelance postings/wk reaching the funnel | mostly via HN | ≥ 30/wk from EU boards directly |

---

## Upgrade 5 — Browser-scraper foundation + Wellfound

### What

A new scraper subtype (`BrowserScraper`) backed by Playwright for sources
that block plain httpx or render listings via JS. First consumer:
**Wellfound** (formerly AngelList Talent) — public listings, no login,
but anti-bot disallows raw httpx.

Three runtime concerns:

1. **Optional dep group.** Playwright adds ~200MB plus a Chromium browser
   download. Goes under `[browser]` in `pyproject.toml`, NOT in the default
   install. CI installs `[dev,browser]` in a dedicated job; the base CI
   matrix stays light.
2. **Crawler routing.** The current crawler passes `httpx.AsyncClient` to
   every scraper. `BrowserScraper.fetch` ignores it. The crawler must
   instantiate a single `playwright.async_api.Browser` once per run, share
   it across all browser scrapers, and run them with bounded concurrency
   (≤ 2) — Chromium contexts are memory-hungry.
3. **Local-vs-VPS execution.** Same risk model as the LinkedIn poster: any
   cookie-bound browser scraper runs from the user's **residential IP**,
   not the Debian VPS. Add a `requires_residential_ip: bool = False` class
   attribute. A new `--exclude-residential` CLI flag (and an env var
   `CAREER_OS_HOST=vps`) skips them automatically when invoked from cron
   on the VPS.

### AngelList note

AngelList Talent was renamed to Wellfound in 2022. Treat them as one source
under the key `wellfound`. Don't add an `angellist` alias — it'd just
duplicate canonical_key (which Tier 1 handles, but better to not need it).

### Files touched

| Path | Change |
|---|---|
| `pyproject.toml` | ADD `[project.optional-dependencies].browser = ["playwright>=1.40.0"]`; document `playwright install chromium` step in README quick-start |
| `src/career_os/scrapers/_browser.py` | NEW — `BrowserScraper` abstract class; `fetch(self, browser: Browser)` signature; `requires_residential_ip` flag |
| `src/career_os/scrapers/wellfound.py` | NEW — opens `wellfound.com/jobs?remote=true&role=engineering`, paginates, yields `JobPost` |
| `src/career_os/scrapers/registry.py` | register `WellfoundScraper`; OK that it's only callable when `[browser]` is installed |
| `src/career_os/crawler/run.py` | route by scraper type: httpx ones in parallel as today; browser ones sequential through a shared `Browser`; skip residential-only scrapers when `CAREER_OS_HOST=vps` |
| `src/career_os/config.py` | read `CAREER_OS_HOST` env var (default: `local`) |
| `src/career_os/cli/main.py` | `fetch --exclude-residential` flag; print skipped scrapers in the result table |
| `tests/test_browser_scraper.py` | NEW — mock `playwright.async_api`; assert page.goto called with the right URL, assert pagination loop terminates |
| `tests/test_crawler.py` | extend — assert VPS run skips residential-only scrapers |
| `.github/workflows/ci.yml` | NEW job `ci-browser` installing `[dev,browser]` + `playwright install chromium`; runs only `tests/test_browser_scraper.py` |

### Acceptance

- `pip install -e ".[browser]" && playwright install chromium` succeeds on
  a clean Python 3.11/3.12 venv.
- `career-os fetch --source wellfound` opens a headless Chromium, scrapes
  one page, yields at least 5 jobs against the real site.
- Run with `CAREER_OS_HOST=vps career-os fetch` from any shell: Wellfound
  is logged as "skipped (residential-only)" and NOT attempted.
- Browser scrapers run sequentially in the crawler; HTTPX scrapers still
  run in parallel. Total wall-time stays under 60s on a healthy run.
- CI's base job (no `[browser]` extras) still passes — Wellfound's test
  file is skipped cleanly via `pytest.importorskip("playwright")`.

### LinkedIn Jobs — defer to a follow-up

Listed in the original Tier 2 scope, but ship Wellfound first because
LinkedIn Jobs needs the cookie-extraction flow + ToS-grey rate-limit
conventions. The `BrowserScraper` + residential-IP routing built for
Wellfound is the foundation; LinkedIn Jobs is one more scraper file on top.
Tracked as Upgrade 5b — same PR-able file shape as Wellfound, with
extra rules: ≤ 50 page-views per session, jittered 4–9s delays, hard
fallback to "skipped (challenge)" on any redirect to `/checkpoint/`.

### Anti-patterns to avoid

- **Don't start the browser in `__init__`.** Lazy-start in the crawler so
  `career-os sources` and import-time don't pay the Chromium boot cost.
- **Don't run browser scrapers in parallel.** Two Chromium contexts ≈ 1GB
  RAM on a low-end laptop. Sequential is fine — the slow source isn't the
  bottleneck for the daily digest.
- **Don't hardcode cookies.** Cookie-based scrapers (LinkedIn Jobs) read
  from `.env` exactly like the LinkedIn poster: `LINKEDIN_LI_AT`,
  `LINKEDIN_JSESSIONID`, `LINKEDIN_BCOOKIE`. Reuse the existing names.
- **Don't add stealth plugins.** `playwright-stealth` etc. are an
  arms-race. The combination of residential IP + human-like timing + cap
  on page-views per session is enough for low-volume daily scraping.

---

## Upgrade 6 — Incremental fetch with watermarks

### What

A per-source watermarks table tracking the last successful fetch.
Three classes of watermark:

| Source type | Watermark used | How |
|---|---|---|
| RSS (WeWorkRemotely) | `If-Modified-Since` + `ETag` | Send both; on 304, the scraper yields nothing and the crawler records `unchanged` |
| JSON API with `created_at` field (Remotive, RemoteOK) | `last_seen_external_id` set OR `max(posted_at)` | Stop iterating once we hit an item already in the watermark |
| Algolia (HN scrapers) | `numericFilters=created_at_i>{cursor}` | Algolia native — server-side filter, no over-fetch |
| Browser (Wellfound) | `max(posted_at)` of canonical jobs seen | Iterate listings until we hit a known one, break |

### Schema diff

```sql
CREATE TABLE IF NOT EXISTS source_watermarks (
    source           TEXT PRIMARY KEY,
    last_fetched_at  TEXT NOT NULL,
    last_status      TEXT NOT NULL,           -- ok | unchanged | partial | failed
    etag             TEXT,
    last_modified    TEXT,
    last_external_id TEXT,
    last_cursor      TEXT,
    notes            TEXT
);
```

Goes through `db/migrations.py` (introduced in Tier 1, Upgrade 2). One
row per source key, upserted at the end of each `_run_one` attempt.

### Files touched

| Path | Change |
|---|---|
| `src/career_os/db/migrations.py` | ADD `source_watermarks` table |
| `src/career_os/db/store.py` | ADD `get_watermark(source)` / `save_watermark(source, **fields)` helpers |
| `src/career_os/scrapers/base.py` | extend interface: `async def fetch(self, ctx) -> AsyncIterator[JobPost]` where `ctx` carries optional `watermark` (back-compat default = None, so existing scrapers don't change shape) |
| Each existing scraper | OPT-IN to watermark use one at a time. RSS first (cheapest win — server-side 304s). Then JSON sources. HN cursors last (they're already date-filtered, just need to remember the cursor). |
| `src/career_os/crawler/run.py` | read watermark before calling `fetch`; write after; if no items + status `unchanged`, log it that way (not as 0-new) |
| `src/career_os/cli/main.py` | `fetch --since-source-watermark / --full-refresh` flags; default is watermarked |
| `src/career_os/dashboard/queries.py` | `source_health` query joins `source_watermarks` to show "unchanged" vs "0 new" distinctly |
| `tests/test_watermarks.py` | NEW — per-source-type cases with respx |

### Acceptance

- First `career-os fetch` after migration: every source runs as today,
  watermarks populated.
- Second `fetch` 5 minutes later: WWR returns 304 (logged `unchanged`),
  Remotive/RemoteOK iterate until `last_external_id` then stop, HN scrapers
  pass `created_at_i>cursor` and return only new items.
- `career-os fetch --full-refresh` ignores watermarks (escape hatch for
  debugging or after schema migrations that change parsing).
- Dashboard distinguishes `0 new (unchanged)` from `0 new (failed)`.
- Tier 1's reconciliation step (dedup) still runs after each watermarked
  fetch — watermarks don't disable canonical_key rebuilding for newly-fetched
  rows.

### Anti-patterns to avoid

- **Don't watermark by `fetched_at`.** Watermarks must use source-side
  fields (`posted_at`, `external_id`, Algolia cursor). Clock skew between
  the source and the local DB makes `fetched_at` lossy.
- **Don't share one watermark across multiple endpoints of the same
  scraper.** WWR has two RSS feeds; each gets its own row keyed by `<scraper
  key>:<category>`.
- **Don't skip the watermark write on failure.** Always record the attempt
  with `last_status=failed`. The dashboard's source-health depends on it
  to flag stale sources.
- **Don't conflate "no new jobs" with "haven't fetched recently."** The
  dashboard's source-health table is the user's only signal that a board
  has been silently broken for a week.

---

## Upgrade 7 — EU freelance boards

### What

Add 3–4 EU-focused freelance scrapers using the
[`add-scraper`](../.claude/skills/add-scraper/SKILL.md) skill. Two reasons
EU-specific:

1. The user's positioning targets EU-remote + EU-timezone freelance
   (positioning.md). HN "Seeking freelancer?" skews US.
2. EU clients pay in EUR and expect EUR-denominated rates, which makes the
   floor filter (Tier 1, Upgrade 1) cleaner — no FX conversion in the hot
   path.

### Source recon (do this BEFORE writing any scraper)

Confirm each source is reachable + parseable without auth or login:

| Candidate | First check | Likely shape | Risk |
|---|---|---|---|
| **Freelancermap** | `curl -sI https://www.freelancermap.com/projects.rss?keywords=laravel` | RSS, public — easiest first scraper | Low — RSS pattern matches WWR |
| **Malt** | `curl -sIL https://www.malt.com/projects` | HTML; some listings public, others login-gated; might need Playwright | Medium — may end up under Upgrade 5 (browser-only) |
| **Worksome** | `curl -sIL https://www.worksome.com/find-work/discover` | HTML; check if Cloudflare-fronted | Medium |
| **Useme** | `curl -sIL https://useme.com/en/jobs/` | HTML; Polish-origin but English UI; check pagination | Low–Medium |
| **Comatch / Expertlead** | Public landing only | Both gate listings behind onboarding | **Drop — login wall** |
| **Toptal** | Public landing only | Jobs invisible to non-vetted users | **Drop — login wall** |

Recon = a single `curl` per source documented in a markdown comment at
the top of the new scraper file. If a source needs Playwright, it goes
under Tier 2 Upgrade 5's `BrowserScraper` base; otherwise httpx.

### Files touched

Per the `add-scraper` skill, each source is:

| Path | Change |
|---|---|
| `src/career_os/scrapers/<key>.py` | NEW scraper file |
| `src/career_os/scrapers/registry.py` | one-line import + add to REGISTRY |
| `tests/test_<key>_scraper.py` | respx-mocked round-trip test (or playwright mock if browser-based) |
| `presence/posts/` (optional) | once 3 EU sources live → one build-in-public post worth shipping |

Don't bundle multiple sources in one PR — small, reversible, one source
per commit (the skill's commit-message shape covers this).

### Channel detection rule

EU freelance boards are channel-pure (every listing IS freelance/contract).
Hard-code `channel=Channel.FREELANCE` at the source level. Don't look at
description keywords — the skill's anti-pattern section warns against
this and it's especially trap-y for EU boards where "permanent" sometimes
means "long-term contract."

### Acceptance

- At least 2 EU sources land: Freelancermap (RSS) confirmed first, then
  one of Malt / Worksome / Useme.
- Each new source has its own respx test fixture.
- `career-os sources` lists them.
- After one warm `career-os fetch`, the dashboard source-health table
  shows non-zero `last_24h` for the new sources.
- `top --channel freelance --min-fit 65` surfaces postings from at least
  two of the new sources after a real run (sanity-check that EU postings
  match the user's profile).

### Anti-patterns to avoid

- **Don't translate descriptions.** Even if the source is German/Polish,
  store the original. The scorer prompt handles multilingual inputs;
  pre-translation introduces drift between what we display and what we
  scored.
- **Don't add login-gated sources** (Comatch, Expertlead, Toptal) just
  because they "would have great matches." The auth + ToS surface area is
  too large for the return. Revisit only if the user gets into one of those
  marketplaces organically.
- **Don't filter by EUR floor at fetch time.** That's Tier 1's job. The
  scraper's only responsibility is faithful ingestion; floor enforcement
  happens at score-time via `filters.py`.

---

## Implementation order

```
1. Upgrade 6 — Watermarks            (independent; biggest perf win; ship first)
2. Upgrade 5 — Browser foundation + Wellfound  (foundational for 5b)
   5b. LinkedIn Jobs (later PR, same module shape)
3. Upgrade 7 — EU freelance boards   (uses add-scraper skill; one source per PR)
```

Watermarks first because the per-source 304/cursor logic is also what
makes Tier 3's stale-job detection cheap (re-checks become "what changed
since last watermark" instead of "fetch all 1,200 jobs again").

## Commit message shape

```
Crawler Tier 2 (1/n): source watermarks + If-Modified-Since on RSS
Crawler Tier 2 (2/n): BrowserScraper base + Wellfound (residential-only)
Crawler Tier 2 (3/n): LinkedIn Jobs scraper (cookie path, residential-only)
Crawler Tier 2 (4/n): Freelancermap scraper (EU RSS)
Crawler Tier 2 (5/n): Malt scraper (browser path)
Crawler Tier 2 (6/n): Worksome scraper
```

## Out of scope (explicit — do NOT bundle)

- **Stale-job detection** (re-check URL, mark closed). Watermarks make it
  cheap, but it's Tier 3.
- **Notifications on high-fit jobs.** Tier 3.
- **Postgres swap-in.** Independent track. Watermarks table is SQLite-shaped
  but Postgres-compatible.
- **Anti-bot evasion beyond residential IP + jitter.** If a source actively
  detects our scraping, we drop it — not escalate.
- **Wellfound login flow.** Public listings only. The moment we'd need an
  account, it goes in the LinkedIn-Jobs-style residential-cookie bucket
  with the same ToS warnings.

## Open questions

1. **Wellfound legal posture.** Their ToS allows public viewing but not
   automated scraping. Are we comfortable running it under the same
   "residential IP + low volume + clipboard fallback on challenge"
   risk-management as the LinkedIn poster, or treat Wellfound as
   manual-only?
2. **Cron on VPS.** Once watermarks land, the daily fetch is cheap enough
   to cron on the VPS. Confirm the residential-only routing (env var
   `CAREER_OS_HOST=vps` in the cron environment) is the right gate, vs.
   a per-source allowlist.
3. **Playwright in CI.** The dedicated `ci-browser` job adds 60–90s per CI
   run and bandwidth for the Chromium download. Cache the browser binary
   between runs via `actions/cache`, or skip browser tests in CI entirely
   and rely on local smoke?

Resolve before starting Upgrade 5 (browser foundation). Upgrade 6
(watermarks) is independent and can ship while these are open.

---

## Cross-links

- Tier 1: [`./tier1-crawler-quality.md`](./tier1-crawler-quality.md)
- Scraper recipe: [`../.claude/skills/add-scraper/SKILL.md`](../.claude/skills/add-scraper/SKILL.md)
- LinkedIn poster precedent (residential-IP + cookie pattern): see
  `presence/cross-posting.md` and the project memory entry on
  `presence/site-snippets/`.
