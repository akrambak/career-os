# Tier 1 — Crawler funnel quality

**Goal:** raise the signal-to-noise ratio of `career-os top` and `career-os
digest` without adding new sources. Make the existing pipeline sharper so
Tier 2 (Wellfound, Playwright, EU boards) doesn't just pull more low-fit
jobs into the funnel.

**Why this comes before Tier 2:** today every new scraper multiplies noise.
Cross-posted roles get stored 3×, freelance posts well below the €60/hr
floor still reach Claude, and one transient 5xx zeroes out a source for
the run. Fixing those four is invisible publicly but it directly serves O1
(land work) by raising the avg fit-score of what surfaces in `top`.

**Non-goal:** new scrapers, dashboard pages, Postgres swap-in, or any
prompt changes to the scorer. Those are separate work-streams.

---

## Success metrics

Measured by running `career-os fetch && career-os score && career-os top
--limit 50` before and after on the same SQLite snapshot:

| Metric | Today | Target after Tier 1 |
|---|---|---|
| Duplicate (canonical_key collision) rate among ingested jobs | unknown — currently impossible to measure | < 5% |
| Jobs reaching the Claude scorer that violate a hardcoded deal-breaker | unknown | 0 |
| Tokens billed per `score --limit 50` run | baseline | ≥ 25% lower |
| Avg fit-score of top-20 results | baseline | ≥ 5 points higher |
| Per-source failure rate causing 0 jobs for the run | one bad request kills the source | retried 3× before giving up |

The first run after merging is the new baseline. The eval harness
(`career-os eval`) keeps the scorer calibrated independently.

---

## Upgrade 1 — Pre-scoring filter

### What

Drop obvious no-fits before they reach `score_pending()`. Filter rules are
read from `Profile.deal_breakers` (already exists, currently unused at
crawl/score time) plus a small set of structured rules baked into a new
`filters.py` module:

- **On-site only** — drop if `location` doesn't match any of: remote,
  worldwide, anywhere, EU-remote, EMEA-remote, or the user's location.
- **Short freelance** — drop freelance postings whose brief explicitly
  states < 2-week scope (regex on description: `(?i)\b(1[- ]?week|short
  gig|few days)\b`).
- **Below floor** — drop freelance postings whose parsed hourly rate (see
  Upgrade 3) is < €60/hr equivalent.
- **Dealbreaker keyword** — case-insensitive substring match against any
  entry in `Profile.deal_breakers` in `title` + `description`.

Reasons are surfaced in a new `filtered_jobs` view so we can audit why a
job got dropped — silent filtering is a debugging trap.

### Files touched

| Path | Change |
|---|---|
| `src/career_os/filters.py` | NEW — `should_drop(job, profile) -> tuple[bool, str \| None]` |
| `src/career_os/scorer/__init__.py` | `score_pending` calls filter; on drop, records a `filtered` row instead of a `score` row |
| `src/career_os/db/store.py` | ADD `filtered_jobs (job_key, reason, filtered_at)` table + `filtered(...)` helper |
| `src/career_os/cli/main.py` | `score` command prints a "filtered N (reasons: …)" line |
| `src/career_os/dashboard/queries.py` | ADD `filter_summary(store)` query |
| `src/career_os/dashboard/pages/overview.py` | Show filtered-by-reason histogram next to source-health |
| `tests/test_filters.py` | NEW — table-driven cases per rule |

### Acceptance

- A job matching any rule is in the `filtered_jobs` table after `score`,
  NOT in the `scores` table. Re-running `score` does NOT re-process it.
- `career-os score --limit 50` prints `Scored N · Filtered M (on-site:X,
  floor:Y, short:Z, kw:W)`.
- Filter reasons appear in the dashboard Overview page below source-health.
- `Profile.deal_breakers` change is picked up on next `score` (no migration).

### Anti-patterns to avoid

- Don't infer floor from the job description with regex — use the parsed
  salary from Upgrade 3. If salary parsing returns `None`, the rule abstains
  (don't drop). Floor filtering should only fire when there's a real number.
- Don't filter at `fetch` time. Keep the raw `jobs` table comprehensive so
  rule changes don't require a re-crawl.

---

## Upgrade 2 — Cross-source dedup

### What

Compute a `canonical_key = sha256(normalize(title) + "|" + lower(company)
+ "|" + normalize(location))[:16]` and store it on the `jobs` table.
During `crawl`, after the per-source upsert loop, run a reconciliation
step: for each `canonical_key` group, keep the row with the most-recent
`fetched_at` and mark the others `is_duplicate = 1`.

Top-level queries (`top_scored`, `top_matches`, digests) filter
`is_duplicate = 0`. The duplicates stay in the DB for auditing — never
deleted — so we can validate the dedup rate retroactively.

`normalize(s)` = lowercase, strip punctuation, collapse whitespace,
remove `(remote)`/`- remote`/`/remote` suffixes.

### Schema diff

```sql
ALTER TABLE jobs ADD COLUMN canonical_key TEXT;
ALTER TABLE jobs ADD COLUMN is_duplicate INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_jobs_canonical_key ON jobs(canonical_key);
CREATE INDEX IF NOT EXISTS idx_jobs_is_duplicate ON jobs(is_duplicate);
```

`Store._init_schema` is idempotent — but `ALTER TABLE ADD COLUMN` is not
expressible in the current `CREATE TABLE IF NOT EXISTS` block. Use a small
migration helper that introspects `PRAGMA table_info(jobs)` and adds the
columns if absent. Don't touch the existing schema string for new tables
— this is the first non-additive change to the jobs table and the project
explicitly wants a "Postgres-shaped" schema, so do the migration cleanly.

### Files touched

| Path | Change |
|---|---|
| `src/career_os/db/migrations.py` | NEW — `apply_migrations(conn)`, called from `_init_schema` |
| `src/career_os/db/store.py` | hook migrations; add `canonical_key` column reads; filter `is_duplicate=0` from top-N queries |
| `src/career_os/models.py` | ADD `canonical_key` + `is_duplicate` (default 0) to `JobPost` |
| `src/career_os/dedup.py` | NEW — `canonical_key(title, company, location) -> str`; `normalize(s) -> str` |
| `src/career_os/crawler/run.py` | after `_run_one` loop, call `reconcile_duplicates(store)` |
| `src/career_os/cli/main.py` | `fetch` prints "Deduped K, kept-newest"; new `career-os dedup --recompute` to backfill |
| `tests/test_dedup.py` | NEW — normalize, canonical_key, reconcile cases |

### Acceptance

- Same `(title, company, location)` posted on RemoteOK and WeWorkRemotely
  produces one canonical row in queries; the older row has `is_duplicate=1`.
- Re-running `fetch` is stable: if the source posted again with same content
  but newer `fetched_at`, that row becomes canonical and previous flips.
- `career-os dedup --recompute` walks every job, recomputes canonical_key,
  and re-runs reconciliation. Idempotent.
- Dashboard `Overview` "Jobs ingested" metric splits into "Jobs (1,234) ·
  Canonical (987)".

### Anti-patterns to avoid

- Don't fuzzy-match (Levenshtein, etc.). Stick to deterministic
  normalization — false positives in dedup are worse than misses, because
  they hide opportunities.
- Don't delete duplicate rows. They're cheap and necessary for auditing.
- Don't compute canonical_key inside `_parse` per scraper — keep it
  centralized in `dedup.canonical_key()` so the rule changes in one place.

---

## Upgrade 3 — Salary parsing

### What

Add a `salary.py` module that exposes:

```python
@dataclass(frozen=True)
class Compensation:
    min_amount: float | None
    max_amount: float | None
    currency: str | None       # ISO 4217 if recognized, else None
    period: str | None         # "year" | "month" | "day" | "hour" | None
    raw: str                   # original string

def parse(text: str | None) -> Compensation
```

Parses every shape we see in the existing 5 scrapers:

| Input | Output |
|---|---|
| `"$80,000 – $120,000"` | min=80000, max=120000, currency=USD, period=year |
| `"€60/hr"` | min=60, max=60, currency=EUR, period=hour |
| `"150k EUR"` | min=150000, max=150000, currency=EUR, period=year |
| `"USD 6500/mo"` | min=6500, max=6500, currency=USD, period=month |
| `"from $90k"` | min=90000, max=None, currency=USD, period=year |
| `""` / `None` / `"Competitive"` | all-None Compensation (raw preserved) |

Currency normalization: `$` → USD, `€` → EUR, `£` → GBP, `¥` → JPY,
explicit ISO codes pass through.

Period heuristics: presence of `/hr|hour|hourly` → hour; `/mo|month|mo` →
month; `/day|daily` → day; otherwise year. Yearly amounts ≥ 1000 are
treated as full; integers 30–500 with no unit are ambiguous → return
period=None (Upgrade 1's floor filter abstains).

EUR-equivalent conversion for the floor filter uses a static rate table
in `salary.py` (USD 1.07, GBP 0.85, …) — no live FX. Refresh quarterly.

### Files touched

| Path | Change |
|---|---|
| `src/career_os/salary.py` | NEW — `parse`, `to_eur_hourly`, rate table |
| `src/career_os/models.py` | ADD `parsed_compensation: Compensation \| None` field on `JobPost` (computed at parse-time, not stored — or store as JSON for retrieval speed) |
| `src/career_os/db/store.py` | Optional: persist `comp_min`, `comp_max`, `comp_currency`, `comp_period` columns via migration so dashboard can filter without re-parsing |
| Each scraper `_parse` | Replace ad-hoc salary string assembly with `salary.parse(...)` call where the source already provides structured fields (RemoteOK has `salary_min`/`max`; Remotive has `salary`) |
| `src/career_os/filters.py` | Reads parsed comp to enforce hourly floor |
| `tests/test_salary.py` | NEW — table-driven, ≥ 30 fixture strings drawn from real prod data |

### Acceptance

- `salary.parse` returns the same `Compensation` for every fixture in
  `tests/test_salary.py`. Unknown input → all-None, never raises.
- RemoteOK + Remotive jobs surface parsed min/max/currency/period in the
  dashboard's top-matches table (replace the current `compensation` free-text).
- A freelance job at €40/hr is filtered (Upgrade 1) with reason
  `floor:40eur_per_hour`.
- A job with `salary=None` is NEVER filtered for floor (rule abstains).

### Anti-patterns to avoid

- Don't pull `babel`, `price-parser`, or any heavyweight dep — this is
  regex + a small table.
- Don't try to extract salary from `description` text. Only parse what the
  scraper already surfaces as a structured/numeric field or a clear
  compensation string. Description-mining belongs in Tier 3 (NER pass).
- Don't store EUR-converted values. Store native + currency, convert on
  read. FX rates drift; the conversion is for filtering, not record-keeping.

---

## Upgrade 4 — Per-source retry + jitter

### What

Wrap `_run_one` in `crawler/run.py` with `tenacity` (already in deps —
used by the scorer and drafter). Three attempts, exponential wait 2s →
20s with full jitter. Retry only on `httpx.HTTPError` and `asyncio.TimeoutError`.

Crucially: the retry wraps the **whole `fetch` iterator**, not individual
items. A partial yield + crash currently loses the work-in-progress jobs
from that pass; with the wrap, the second attempt re-iterates from scratch
(scrapers are read-only HTTP so this is safe).

Per-source backoff metadata goes into a new `crawl_log` table so we can
inspect:

```sql
CREATE TABLE IF NOT EXISTS crawl_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    run_started_at  TEXT NOT NULL,
    attempts        INTEGER NOT NULL,
    final_status    TEXT NOT NULL,    -- ok | failed | partial
    jobs_yielded    INTEGER NOT NULL,
    error_type      TEXT,
    error_detail    TEXT,
    duration_ms     INTEGER NOT NULL
);
```

### Files touched

| Path | Change |
|---|---|
| `src/career_os/crawler/run.py` | wrap `_run_one` with `tenacity.AsyncRetrying`; emit one `crawl_log` row per run × source |
| `src/career_os/db/migrations.py` | add `crawl_log` table |
| `src/career_os/dashboard/queries.py` | extend `source_health` to surface last_status + last_error per source |
| `src/career_os/dashboard/pages/overview.py` | source-health table grows a "last status" column |
| `tests/test_crawler.py` | NEW — `respx` mock that returns 503 twice then 200, asserts 3 attempts + 200's items reach the store |

### Acceptance

- A source returning `503` then `503` then `200` yields the 200's items.
  `crawl_log` records 3 attempts, `final_status=ok`.
- A source returning `503` thrice gives up; `crawl_log` records
  `final_status=failed`, `error_type=HTTPError`, no jobs lost from other
  sources.
- `career-os fetch` total wall-time on a healthy run does NOT regress
  (no retry triggered when the first attempt succeeds).
- Dashboard source-health shows "last status: ok 2s ago" or
  "failed 3× — TimeoutError".

### Anti-patterns to avoid

- Don't retry inside a scraper's `fetch`. The crawler is the single retry
  layer — multiple retry layers make CI logs unreadable when something
  goes wrong.
- Don't retry on `httpx.TooManyRedirects` or `JSONDecodeError`. Those are
  scraper bugs, not transient errors. Retrying masks them.
- Don't set `stop_after_attempt(>3)`. If a source is down for 3 attempts
  spread over 30s, it's not coming back this run. Move on.

---

## Implementation order

```
1. Upgrade 3 — Salary parsing       (foundational; Upgrade 1's floor depends on it)
2. Upgrade 1 — Pre-scoring filter   (depends on Upgrade 3 for parsed comp)
3. Upgrade 2 — Cross-source dedup   (independent; can ship before or after 1+3)
4. Upgrade 4 — Retry + jitter       (independent; ship last, smallest blast radius)
```

Each upgrade is a separate PR. Acceptance criteria per upgrade are testable
in isolation. The new modules (`filters.py`, `dedup.py`, `salary.py`,
`db/migrations.py`) land before they're wired into the CLI / dashboard, so
each PR is small and reversible.

## Commit message shape

Match recent project history:

```
Crawler Tier 1 (1/4): salary parsing — structured min/max/currency/period
Crawler Tier 1 (2/4): pre-scoring filter — enforce dealbreakers + floor
Crawler Tier 1 (3/4): cross-source dedup — canonical_key + is_duplicate
Crawler Tier 1 (4/4): per-source retry + crawl_log
```

## Out of scope (explicit — do NOT bundle)

- New scrapers (Wellfound, EU boards). Those are Tier 2 and use the
  `add-scraper` skill.
- Playwright. Tier 2.
- Postgres swap-in. Tracked in README Phase 1 backlog independently.
- Stale-job detection, change-diff, watch-lists. Tier 3.
- Any scorer prompt changes. Calibration is guarded by the eval harness;
  don't touch it from a crawler PR.

## Open questions

1. **Hourly floor amount and currency** — README says "€60/hr"; the drafter
   says the same. Confirm this is the single source of truth, or move it
   to `Profile`.
2. **Location matching** — user's location for the on-site filter. Hard-code
   to "Algeria" + "EU-remote-acceptable" or add a `Profile.locations: list[str]`?
3. **FX rates** — quarterly manual refresh OK, or should we cache a live
   rate from an open API on first run per quarter?

Resolve before starting Upgrade 1.
