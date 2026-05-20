# Tier 3 — Compounding value

**Goal:** stop the funnel from rotting and start using it as a daily
signal source. Three of these four upgrades only become cheap *because*
[Tier 1](./tier1-crawler-quality.md) (canonical_key) and
[Tier 2](./tier2-crawler-coverage.md) (watermarks) shipped first — Tier 3
is the dividend on that foundation.

**Non-goal:** anything that touches the scorer prompt or the underlying
SQLite-vs-Postgres question. Those are tracked independently. This tier
adds behavior on top of the existing schema + scoring loop.

---

## Success metrics

Measured against the steady-state funnel ~2 weeks after Tier 2 ships:

| Metric | Today | Target after Tier 3 |
|---|---|---|
| `top` results that point to a closed/404 listing | unknown; manually painful | < 2% |
| Median time from a watch-list match landing in the DB → user notified | n/a — no notifications today | < 5 min |
| Avg fit-score of jobs the user **acts on** (apply/draft) | baseline | ≥ 10 points higher (driven by watch-list signal cutting through digest noise) |
| Freelance applications stuck in `replied` when they're actually at `scope_call` | not measurable today — stage shared with FT | 0; freelance pipeline has its own stages |
| Freelance budget-revision detection (jobs whose comp changed after first scrape) | 0 (we overwrite silently) | every revision logged in `job_changes` |

---

## Upgrade 8 — Stale-job detection

### What

A periodic re-check that HEADs each job URL and marks closed/removed
postings so `top`, `digest`, and the dashboard stop surfacing dead links.
Three closed signals:

1. **HTTP 404 / 410** on the URL
2. **HTTP 200 but redirected** to a generic listings page (compare final
   URL hostname+path against the original; pattern-match `/jobs/`,
   `/closed`, `/expired`)
3. **Source-specific markers** (RemoteOK serves a placeholder page;
   Wellfound returns "this position is no longer accepting applications"
   in the rendered HTML). Each scraper exposes an optional
   `is_closed(html_or_response) -> bool` hook; absent = use signals 1+2
   only.

Stale-job detection runs as a separate command (`career-os recheck`) on
its own cadence (weekly cron). Don't fold it into `fetch` — re-check
traffic is large and the failure modes are different from a fresh scrape.

### Schema diff

```sql
ALTER TABLE jobs ADD COLUMN is_closed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN closed_at TEXT;
ALTER TABLE jobs ADD COLUMN last_rechecked_at TEXT;
ALTER TABLE jobs ADD COLUMN recheck_attempts INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_jobs_is_closed ON jobs(is_closed);
CREATE INDEX IF NOT EXISTS idx_jobs_last_rechecked_at ON jobs(last_rechecked_at);
```

Migration via `db/migrations.py` (introduced in Tier 1, extended in Tier 2).

### Files touched

| Path | Change |
|---|---|
| `src/career_os/db/migrations.py` | columns above |
| `src/career_os/db/store.py` | `recheck_candidates(limit, max_age_days)` → jobs with `is_closed=0` and `last_rechecked_at` older than 7d (or null); `mark_closed(key, reason)` |
| `src/career_os/scrapers/base.py` | OPTIONAL `is_closed(response) -> bool` hook on `Scraper` (default returns `False`) |
| `src/career_os/recheck.py` | NEW — async batch HEAD/GET against candidate URLs, bounded concurrency (10), respects per-source `_client_headers()` |
| `src/career_os/cli/main.py` | NEW `career-os recheck [--limit 200] [--source <key>]`; prints summary (closed N, still-live M, errored K) |
| `src/career_os/dashboard/queries.py` | `top_matches` filters `is_closed=0`; ADD `closure_summary()` query |
| `src/career_os/dashboard/pages/overview.py` | "Source health" gets a "closed/week" column |
| `tests/test_recheck.py` | NEW — respx fixtures for 404, 410, redirect-to-listings, source-specific marker, transient 5xx |

### Acceptance

- `career-os recheck --limit 50` HEADs 50 oldest-rechecked jobs and marks
  closed ones with `is_closed=1`, `closed_at=NOW()`, `last_rechecked_at=NOW()`.
- Transient 5xx increments `recheck_attempts` but doesn't mark closed.
  After 3 failed attempts on the same URL across separate runs, mark
  closed with reason `unreachable` (cleaner than letting dead URLs
  linger forever).
- `top` and `digest` no longer surface jobs with `is_closed=1`.
- Re-opened jobs (rare but real — companies sometimes re-list) get
  picked up by the next `fetch` because canonical_key matches the closed
  row, which the upsert path clears (`is_closed=0`) when it sees the
  re-listing.
- Dashboard surfaces a one-line health note: "47 jobs closed this week
  (12 RemoteOK, 9 WWR, …)".

### Anti-patterns to avoid

- **Don't recheck on every fetch.** That's 4× the daily traffic. Weekly
  cron is the right cadence; raise it only if specific sources warrant.
- **Don't delete closed jobs.** They're cheap and they feed `eval` /
  postmortem analysis ("we missed this one"). The funnel filters them
  out — that's enough.
- **Don't trust a single 404.** Some sources serve 404 for unauthenticated
  bots but 200 for browsers (Wellfound does this). For those sources,
  prefer the source-specific `is_closed` hook over generic HTTP-status
  matching.
- **Don't run recheck through the same retry policy as `fetch`.** Recheck
  failures are non-fatal and shouldn't burn the same backoff budget — a
  single attempt per URL per run, with the cumulative-attempts column
  doing the multi-run patience.

---

## Upgrade 9 — Watch lists

### What

User-defined alerts: "any new Wellfound posting mentioning Laravel + AI
with fit ≥ 75 pings my Telegram immediately." Three watch types:

| Type | Match | Example |
|---|---|---|
| **Company** | exact company-name match (case-insensitive) on a canonical job | `Linear` |
| **Keyword** | substring match on `title + tags + description` (all lowercased) | `claude sdk`, `e-commerce`, `prestashop` |
| **Min-fit + filter** | fit ≥ threshold AND optional channel/source filter | `fit≥75 channel=freelance source=wellfound` |

Watches fire AFTER scoring, NOT at fetch time — the user wants signal-
weighted alerts, not noise-weighted. A match emits to one or more
notification channels.

### Notification channels

| Channel | Backend | Env vars | When |
|---|---|---|---|
| **Email** | `DigestEmailer` (re-used) | already wired (`SMTP_PROVIDER`, `SMTP_API_KEY`, `SMTP_FROM`, `SMTP_TO`) | bulk / non-urgent — collapse multiple matches into one email per hour |
| **Telegram** | NEW — Bot API `sendMessage` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | instant per match — Telegram bots are free, no rate-spend, mobile-friendly |
| **Dashboard banner** | session-state notification on next dashboard open | none | always on; failsafe when other channels misconfigured |

No Slack adapter unless explicitly asked — Slack is team-tool overhead
the user doesn't currently need. (`presence/cross-posting.md` lists the
user's actual surfaces.)

### Schema diff

```sql
CREATE TABLE IF NOT EXISTS watches (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,                  -- short label for the dashboard
    watch_type    TEXT NOT NULL,                  -- company | keyword | fit_filter
    pattern       TEXT NOT NULL,                  -- company name, keyword, or JSON filter spec
    min_fit       INTEGER NOT NULL DEFAULT 0,
    channel       TEXT,                           -- 'ft' | 'freelance' | NULL (any)
    notify_email  INTEGER NOT NULL DEFAULT 0,
    notify_tg     INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watch_hits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id        INTEGER NOT NULL REFERENCES watches(id) ON DELETE CASCADE,
    job_key         TEXT NOT NULL REFERENCES jobs(key) ON DELETE CASCADE,
    notified_at     TEXT,
    notification_status TEXT,                    -- ok | failed | suppressed
    UNIQUE(watch_id, job_key)
);
CREATE INDEX IF NOT EXISTS idx_watch_hits_job ON watch_hits(job_key);
```

The `UNIQUE(watch_id, job_key)` constraint is the spam guard — a single
match notifies once, even if `score` reruns over the same job.

### Files touched

| Path | Change |
|---|---|
| `src/career_os/db/migrations.py` | tables above |
| `src/career_os/watches/__init__.py` | NEW module: `Watch` dataclass, CRUD helpers (`list_watches`, `add_watch`, `update_watch`, `delete_watch`, `evaluate(store, job, score) -> list[Watch]`) |
| `src/career_os/notify/__init__.py` | NEW — `Notification` dataclass, `route(watch, hit, ctx)` dispatcher |
| `src/career_os/notify/telegram.py` | NEW — `send_telegram(token, chat_id, text) -> Result`; minimal markdown-safe escaping |
| `src/career_os/notify/email.py` | re-export `DigestEmailer` configured for watch-list batches |
| `src/career_os/scorer/__init__.py` | after a successful `score_pending`, evaluate watches for each newly-scored job; record hits; dispatch notifications |
| `src/career_os/dashboard/pages/watches.py` | NEW dashboard page using the [`add-dashboard-page`](../.claude/skills/add-dashboard-page/SKILL.md) skill — list/add/edit/disable watches, show recent hits |
| `src/career_os/dashboard/app.py` | navigation entry |
| `.env.example` | add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| `tests/test_watches.py` | NEW — table-driven match logic per watch_type |
| `tests/test_notify_telegram.py` | NEW — respx mock of the Bot API |

### Acceptance

- A `keyword` watch on `prestashop` fires when a new job's title/tags/
  description contains that string. A second `score` run doesn't re-fire
  (dedup via `UNIQUE(watch_id, job_key)`).
- Telegram delivery: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` set + watch
  with `notify_tg=1` → message arrives in chat with title, fit, channel,
  source, URL. Without the env vars, the watch is recorded as
  `notification_status='suppressed'` — never crashes the scoring run.
- Email delivery: matches accumulate, emailer batches them hourly via a
  separate `career-os notify --send` step (cron from the VPS, same as
  digest). Reuses `DigestEmailer` so no duplicated SMTP code.
- Dashboard `Watches` page: shows active/inactive watches, last-fired
  timestamp per watch, and a recent-hits feed.
- A freelance company-watch on `Linear` does NOT fire on FT postings even
  if the company matches — channel filter is respected.

### Anti-patterns to avoid

- **Don't notify at fetch time.** Pre-scoring noise will burn out the
  notification channel and the user. Watches gate on scored jobs.
- **Don't run notifications inline in the score loop.** Score → record
  hits → dispatch as a separate step. A failing Telegram API must not
  abort scoring.
- **Don't allow regex patterns from the UI.** Substring + exact-company
  match is enough; regex is a foot-gun and a debugging tax.
- **Don't add Slack/Discord adapters speculatively.** Email + Telegram
  cover the user's actual workflow. Each adapter is a maintenance
  surface — only add when asked.
- **Don't store the Telegram bot token in the DB.** Env-only (mirrors
  `ANTHROPIC_API_KEY` and SMTP creds).

---

## Upgrade 10 — Change diff

### What

When a watermarked re-fetch (Tier 2, Upgrade 6) sees a job we already
have, compare key fields and record the diff. Surface "updated" jobs
in the dashboard with a badge and a "what changed" tooltip.

The signal users care about (especially freelance): **compensation
revisions**. A brief posted at €40/hr that gets bumped to €70/hr might
now clear the floor filter; a job pulled from `top` due to budget gap
might re-enter.

### Fields tracked

| Field | Comparison | Why |
|---|---|---|
| `title` | exact string | rename usually means scope shift |
| `compensation` | parsed comp (Tier 1) min/max/period | budget revisions are the highest-value signal |
| `description_hash` | sha256(first 4000 chars) | flag changed bodies without storing every version |
| `tags` | set difference | new stack mentions = relevance change |
| `location` | exact string | rare but happens (remote → hybrid) |

Description bodies themselves are NOT versioned (storage growth) — only
the hash. If the user needs the old body, they re-pull from the source.

### Schema diff

```sql
CREATE TABLE IF NOT EXISTS job_changes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_key       TEXT NOT NULL REFERENCES jobs(key) ON DELETE CASCADE,
    field         TEXT NOT NULL,                  -- title | compensation | description | tags | location
    before_value  TEXT,
    after_value   TEXT,
    detected_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_changes_job ON job_changes(job_key);
CREATE INDEX IF NOT EXISTS idx_job_changes_detected ON job_changes(detected_at);

ALTER TABLE jobs ADD COLUMN description_hash TEXT;
ALTER TABLE jobs ADD COLUMN last_changed_at TEXT;
```

### Files touched

| Path | Change |
|---|---|
| `src/career_os/db/migrations.py` | schema above |
| `src/career_os/db/store.py` | `upsert_job` becomes change-aware: on existing key, diff fields → write to `job_changes` + update `last_changed_at` |
| `src/career_os/changes/__init__.py` | NEW — `diff_job(old, new) -> list[Change]`; `recent_changes(store, since)` |
| `src/career_os/dashboard/queries.py` | `top_matches` returns a `changed_recently` boolean; ADD `recent_changes_feed()` |
| `src/career_os/dashboard/pages/overview.py` | "Top matches" rows render an "updated" badge when `changed_recently`; new "Recent changes" panel |
| `src/career_os/cli/main.py` | `career-os changes [--since 7d]` prints a table of recent diffs |
| `src/career_os/scorer/__init__.py` | rescoring trigger: if a `compensation` or `description_hash` change is detected, mark the existing score stale → `score` re-processes it next run |
| `tests/test_changes.py` | NEW — diff logic table-driven; integration test that upserting an existing job with new comp writes a `job_changes` row |

### Acceptance

- A second `fetch` after a source bumps its salary range from €60–80k to
  €70–100k writes one `job_changes` row with `field=compensation`.
- The job's `last_changed_at` is updated. `top` rendering shows an
  "updated" badge for jobs whose `last_changed_at` is within 7 days.
- `career-os changes --since 7d` shows a table of recent diffs grouped by
  field type.
- A `compensation` diff invalidates the existing score (the row is removed
  from `scores`); next `score` run reprocesses the job and may now pass
  Tier 1's floor filter.
- Description-only edits (typo fixes, etc.) below a small word-count
  threshold are NOT flagged. Only diffs ≥ N% of description length count.

### Anti-patterns to avoid

- **Don't store every description version.** Hash + change-event is
  enough. Full versioning balloons the SQLite file without proportional
  value.
- **Don't auto-rescore on tag-only or location-only diffs.** They rarely
  change the fit calculation. Only rescore on compensation /
  description_hash changes.
- **Don't surface every diff in the dashboard.** Filter to "interesting
  changes" — comp diffs always, description diffs above the threshold,
  title diffs always, tag/location diffs only in `career-os changes`.
- **Don't diff `fetched_at` or scraper metadata fields.** Those change
  every run and would dominate `job_changes`.

---

## Upgrade 11 — Per-channel pipeline

### What

Today's `STAGES` tuple in `tracker/pipeline.py` is shared between FT and
freelance applications. That conflates two real workflows:

```
FT:        drafted → sent → replied → interview → offer → won/rejected/dropped
Freelance: drafted → sent → scope_call → proposal_sent → signed_proposal → won/rejected/dropped
```

Freelance has no `interview` stage — it has a scope call and then a
written proposal. FT has no `proposal_sent` — they have one or more
interviews and an offer. Lumping them means the funnel display is
truthful for one channel and wrong for the other.

### Approach

Two stage tuples, one shared terminal set:

```python
FT_STAGES = ("drafted", "sent", "replied", "interview", "offer")
FREELANCE_STAGES = ("drafted", "sent", "scope_call", "proposal_sent", "signed_proposal")
TERMINAL = ("won", "rejected", "dropped")

STAGES_BY_CHANNEL = {"ft": FT_STAGES, "freelance": FREELANCE_STAGES}
```

Applications carry a `channel` column populated at `record_application`
time from the linked job's channel. `advance(store, key)` reads the
channel and walks the right tuple. `funnel_counts` returns nested
`{channel: {stage: n}}` instead of a flat dict.

### Schema diff

```sql
ALTER TABLE applications ADD COLUMN channel TEXT NOT NULL DEFAULT 'ft';
CREATE INDEX IF NOT EXISTS idx_applications_channel ON applications(channel);
```

Backfill: set every existing row's `channel` from the linked job.

### Files touched

| Path | Change |
|---|---|
| `src/career_os/db/migrations.py` | column + backfill in one transaction |
| `src/career_os/tracker/pipeline.py` | introduce `STAGES_BY_CHANNEL`, `TERMINAL`; `record_application` reads job channel; `advance` is channel-aware; `funnel_counts` returns nested |
| `src/career_os/cli/main.py` | `apply`/`advance` `--stage` choices populate from the channel; `status` prints two funnels side by side |
| `src/career_os/dashboard/queries.py` | `funnel()` returns nested dict |
| `src/career_os/dashboard/pages/overview.py` | render two stacked funnels (FT, freelance) instead of one |
| `tests/test_tracker.py` | extend — per-channel transitions; cross-channel transition is rejected |

### Acceptance

- An application linked to a freelance job created via `career-os apply
  <key>` starts at `drafted`, advances to `sent → scope_call →
  proposal_sent → signed_proposal → won`. The `interview` stage is
  unreachable on this channel.
- An FT job's application advances to `interview → offer → won` and
  cannot enter `scope_call`.
- `career-os status` prints two funnels: "FT pipeline" and "Freelance
  pipeline", each summing to its own total.
- Dashboard Overview shows two funnel widgets stacked, each with the
  channel-specific stages.
- Migration is idempotent: re-running it on an already-migrated DB is a
  no-op (column-exists check in `db/migrations.py`).

### Anti-patterns to avoid

- **Don't introduce a separate `freelance_applications` table.** The data
  is the same shape — channel is a column, not a table split. Split-table
  approaches scatter the funnel logic and break the existing
  `JOIN jobs` queries.
- **Don't make stages mutable from the UI.** The two tuples are project
  decisions, not user preferences. Editing them is a code change.
- **Don't repurpose `replied` as `scope_call` for freelance.** Rename
  cleanly. The two pipelines are different workflows; conflating stage
  names defeats the upgrade.

---

## Implementation order

```
1. Upgrade 11 — Per-channel pipeline   (independent of Tier 1/2; biggest immediate UX win)
2. Upgrade 8  — Stale-job detection    (needs Tier 2 watermarks for cheap re-checks)
3. Upgrade 9  — Watch lists            (needs Tier 1 canonical_key for hit dedup)
4. Upgrade 10 — Change diff            (most complex; needs Tier 1 parsed comp + Tier 2 re-fetch loop)
```

Reasoning: 11 first because it's the only one with zero dependency on
Tier 1/2 and it cleans up the funnel display before more data lands on
top. 8 next because watermarks make the re-check sample tiny. 9 is the
biggest behavior change (notifications) and benefits from a clean funnel
+ live recheck data. 10 last — the most schema-and-flow-heavy, and the
most "nice to have" relative to acting on signal.

## Commit message shape

```
Crawler Tier 3 (1/n): per-channel pipeline (FT vs freelance stages)
Crawler Tier 3 (2/n): stale-job detection + career-os recheck command
Crawler Tier 3 (3/n): watch lists + Telegram adapter
Crawler Tier 3 (4/n): change-diff detection + job_changes feed
```

## Out of scope (explicit — do NOT bundle)

- **Slack / Discord adapters.** Email + Telegram cover the user's
  workflow. Skip unless explicitly requested.
- **Webhook ingest** (sources push to us instead of us pulling). Different
  problem class — defer until at least one source supports it natively.
- **AI-generated digests** ("here's what changed this week, summarized").
  Tempting, but the user's scorer + outreach drafter already burn Claude
  tokens; a third Claude consumer needs its own ROI case.
- **Bidirectional pipeline sync** (CRM, Notion, Airtable). The pipeline
  table IS the source of truth.
- **Mobile push notifications.** Telegram already delivers to mobile.

## Open questions

1. **Telegram chat target.** Single user chat (cleanest), or a private
   channel the user owns (more flexible if other people are added later)?
   `TELEGRAM_CHAT_ID` supports both — pick the convention before Upgrade 9.
2. **Recheck cadence.** Weekly is the default in this spec. Should
   freelance postings (shorter half-life) be rechecked every 3 days while
   FT stays weekly? Adds a `recheck_interval_days` per-source override.
3. **Closed-job re-open semantics.** When `fetch` sees a closed job's
   canonical_key again, should it auto-reopen (clear `is_closed`) or just
   create a duplicate that the dedup step keeps as canonical? Auto-reopen
   is cleaner; explicit confirmation in this doc lands the choice.
4. **Migration of existing applications.** All existing rows are FT-stage
   by default. Any application linked to a freelance job will get its
   channel set correctly, but the stage may need manual remapping (e.g.,
   `replied` → `scope_call`). Should the migration attempt that mapping,
   or leave it as a one-time manual step?

Resolve before starting Upgrade 9 (Telegram) and Upgrade 11 (migration).

---

## Cross-links

- Tier 1: [`./tier1-crawler-quality.md`](./tier1-crawler-quality.md)
- Tier 2: [`./tier2-crawler-coverage.md`](./tier2-crawler-coverage.md)
- Dashboard page recipe: [`../.claude/skills/add-dashboard-page/SKILL.md`](../.claude/skills/add-dashboard-page/SKILL.md)
- Existing email infra (re-used by watch-list email batches):
  `src/career_os/digest/email.py`
- Existing tracker (extended by Upgrade 11): `src/career_os/tracker/pipeline.py`
