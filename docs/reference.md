# Career-OS — function reference

Auto-generated walkthrough of the public surfaces. CLI commands first
(daily-driver), then the Python API grouped by module.

If a name isn't here, it's intentionally internal (underscore-prefixed) or
a UI page that doesn't have a stable Python entrypoint.

---

## 1. CLI — `career-os <command>`

Installed by `pip install -e ".[dev]"`. Run any command with `--help` for
flags.

| Command | What it does |
|---|---|
| `career-os sources` | List registered scrapers (key + class name). |
| `career-os fetch [--source KEY] [--full-refresh]` | Run scrapers concurrently, upsert new postings. `--full-refresh` ignores watermarks and re-pulls everything. Prints per-source new-count + status. |
| `career-os score [--limit 50] [--dry-run]` | Score unscored jobs against your profile via Claude. `--dry-run` uses a keyword stub (no API key). |
| `career-os top [--limit 5] [--min-fit 60] [--channel ft\|freelance\|either\|all]` | CLI table of top-scored jobs. Closed jobs hidden. |
| `career-os digest [--limit 5] [--min-fit 60] [--out PATH] [--send]` | Render Markdown digest of top matches. `--send` ships it via `SMTP_PROVIDER`. |
| `career-os draft [JOB_KEY \| --top N] [--min-fit 70] [--dry-run]` | Generate outreach drafts (FT cover OR freelance pitch). |
| `career-os apply JOB_KEY [--stage drafted] [--notes ...]` | Add a job to the pipeline tracker. Stage must match the job's channel pipeline. |
| `career-os advance JOB_KEY [--to STAGE] [--notes ...]` | Move along the per-channel pipeline (default: next stage). |
| `career-os status [--stage STAGE] [--channel ft\|freelance]` | Print per-channel funnels (FT + Freelance) + recent applications. |
| `career-os eval [--dry-run]` | Run scorer fixtures, assert distribution is calibrated. |
| `career-os recheck [--limit 200] [--max-age-days 7] [--source KEY] [--concurrency 10]` | Re-check job URLs; mark 404 / redirect-to-listings / 3-strikes as closed. |
| `career-os dashboard [--port 8501] [--address 0.0.0.0] [--diagnose]` | Launch the Streamlit dashboard. Needs `pip install -e ".[dashboard]"`. `--diagnose` prints WSL networking recipes. |

Daily flow: `fetch && score && top --min-fit 70 && draft --top 5`.

---

## 2. Python API

### `career_os.config`

```python
from career_os.config import Settings

settings = Settings.load()  # reads .env + env vars
```

`Settings` (frozen dataclass) exposes:

| Field | Source | Default |
|---|---|---|
| `anthropic_api_key` | `ANTHROPIC_API_KEY` | None |
| `database_url` | `DATABASE_URL` | `sqlite:///<repo>/data/career_os.db` |
| `smtp_provider` | `SMTP_PROVIDER` | None |
| `smtp_api_key` | `SMTP_API_KEY` | None |
| `smtp_from` | `SMTP_FROM` | `me@bak-dev.com` |
| `smtp_to` | `SMTP_TO` | `me@bak-dev.com` |

---

### `career_os.models`

Pydantic + Enum types shared across the package.

```python
from career_os.models import Channel, JobPost, Score, Profile
```

#### `Channel(StrEnum)`
Values: `FT`, `FREELANCE`, `EITHER`. Used by `JobPost.channel`, `Profile.target_channels`, tracker channel-routing.

#### `JobPost`
Frozen-ish Pydantic model. Key fields:
- `source`, `external_id`, `url`, `title`, `company`, `location`, `description`, `tags`, `channel`
- `compensation: str | None` — raw free-text from the source
- `parsed_compensation: Compensation | None` — structured form (see `salary`)
- `posted_at`, `fetched_at`
- `.key` (property) = `f"{source}:{external_id}"` — stable identity across runs.

```python
job = JobPost(
    source="remoteok", external_id="123", url="https://...",
    title="Senior Laravel + AI", description="...",
    channel=Channel.FT,
)
print(job.key)  # "remoteok:123"
```

#### `Score`
`job_key`, `fit (0-100)`, `reasoning`, `pros`, `cons`, `suggested_angle`, `scored_at`.

#### `Profile`
`name`, `handle`, `headline`, `years_experience`, `proven_stack`, `new_stack`, `target_channels`, `deal_breakers`, `nice_to_haves`. Use `career_os.profile.DEFAULT_PROFILE` for the user's canonical profile.

---

### `career_os.profile`

```python
from career_os.profile import DEFAULT_PROFILE
```

The user's profile (`Profile` instance) fed to scorer + drafter. Edit
`profile.py` to change.

---

### `career_os.salary` — compensation parser (Tier 1 Upgrade 3)

```python
from career_os.salary import parse, parse_from_numeric, Compensation, EMPTY
```

#### `parse(text: str | None) -> Compensation`
Free-text → structured. Never raises. Empty input or vague terms ("Competitive", "DOE") return `EMPTY`.

```python
parse("$80,000–$120,000")
# Compensation(min_amount=80000, max_amount=120000, currency='USD', period='year', raw='$80,000–$120,000')

parse("€60/hr").to_eur_hourly()
# 60.0
```

#### `parse_from_numeric(min_amount, max_amount, currency="USD", period="year", raw=None) -> Compensation`
Skip the regex pass when the source already gives you numbers (RemoteOK's `salary_min`/`salary_max`).

#### `Compensation` (frozen dataclass)
- `min_amount`, `max_amount`, `currency`, `period`, `raw`
- `.known` (property) → `True` if any amount parsed
- `.to_eur_hourly() -> float | None` — EUR-equivalent hourly rate for the floor filter. Abstains (None) when currency or period unknown.

---

### `career_os.watermark` — incremental fetch state (Tier 2 Upgrade 6)

```python
from career_os.watermark import Watermark, WatermarkCtx
```

#### `Watermark` (frozen dataclass)
Per-source persisted state: `source`, `last_fetched_at`, `last_status`, `etag`, `last_modified`, `last_external_id`, `last_cursor`, `notes`.

#### `WatermarkCtx`
Threaded through `Scraper.fetch`. Scrapers opt-in to incremental fetch:

```python
async def fetch(self, client, watermarks: WatermarkCtx | None = None):
    prior = watermarks.get(self.key) if watermarks else None
    # ... use prior.etag, prior.last_external_id, ...
    if watermarks:
        watermarks.record(self.key, status="ok", last_external_id="42")
```

The crawler flushes records to Store via `ctx.flush(store.save_watermark)`.

---

### `career_os.crawler`

```python
from career_os.crawler import crawl, crawl_sync
```

#### `await crawl(store, scraper_keys=None, *, use_watermarks=True) -> dict[str, int]`
Run scrapers concurrently, return `{source_key: new_jobs_count}`. Bad sources can't kill the run — exceptions are caught + watermarked as `failed`.

#### `crawl_sync(store, ...)`
Same but blocking — convenience for non-async callers.

---

### `career_os.db.Store`

```python
from career_os.db import Store
store = Store("sqlite:///data/career_os.db")
```

Schema is created + migrations applied on init (idempotent).

| Method | Purpose |
|---|---|
| `upsert_job(job: JobPost) -> bool` | Insert/update. Returns True if newly inserted. Resets `is_closed` if a previously-closed job is re-seen. |
| `unscored_jobs(limit=50) -> list[JobPost]` | Jobs without a `Score` row. |
| `save_score(score: Score)` | Insert/replace score. |
| `get_job(key) -> JobPost \| None` | One job by `<source>:<id>`. |
| `get_score(job_key) -> Score \| None` | One score. |
| `save_draft(job_key, fmt, body, model, subject=None)` | Persist a drafted outreach. |
| `get_draft(job_key) -> dict \| None` | Read it back. |
| `top_scored(limit=5, min_fit=0) -> list[(JobPost, Score)]` | Highest-fit non-closed jobs. |
| `get_watermark(source) -> Watermark \| None` | Read incremental-fetch state. |
| `save_watermark(*, source, last_fetched_at, last_status, **fields)` | Upsert with `COALESCE` semantics (unspecified fields preserved). |
| `list_watermarks() -> list[Watermark]` | All rows — used by dashboard health join. |
| `recheck_candidates(limit=200, max_age_days=7, source=None) -> list[JobPost]` | Open jobs not rechecked in N days. |
| `mark_closed(key, reason)` | Flip `is_closed=1`, set `closed_at`. Reason is logged, not persisted per-job. |
| `mark_recheck_attempt(key, *, transient: bool) -> int` | Bump or clear `recheck_attempts`. Returns new count — caller decides 3-strikes. |
| `closed_count_since(cutoff_iso) -> dict[str, int]` | Per-source closure counts since a timestamp. |

---

### `career_os.scrapers`

```python
from career_os.scrapers import REGISTRY, get_scraper, Scraper
```

#### `REGISTRY: dict[str, type[Scraper]]`
Keys: `remoteok`, `weworkremotely`, `remotive`, `hn_freelancer`, `hn_whoishiring`. Iterate to enumerate.

#### `get_scraper(key) -> Scraper`
Instantiate by key. Raises `KeyError` for unknown.

#### `Scraper` (abstract base)
Subclass to add a source. Set `key` class attr, implement:
```python
async def fetch(
    self, client: httpx.AsyncClient,
    watermarks: WatermarkCtx | None = None,
) -> AsyncIterator[JobPost]: ...
```
Optional hook:
```python
def is_closed(self, response: httpx.Response) -> bool:
    # Return True if a 200 response indicates a closed listing.
```

Use the `add-scraper` skill (`.claude/skills/add-scraper/`) for the full recipe.

---

### `career_os.scorer`

```python
from career_os.scorer import ClaudeScorer, score_pending
```

#### `ClaudeScorer(api_key, model="claude-sonnet-4-6")`
Wraps the Anthropic client. Uses ephemeral cache on the system prompt.
- `.score(job, profile) -> Score` — 3 retries on transient failures; raises on `AuthenticationError` or bad JSON.

#### `score_pending(store, scorer, profile, limit=50) -> int`
Score every `unscored_job` up to `limit`. Logs and skips per-job failures. Returns count successfully scored.

---

### `career_os.drafter`

```python
from career_os.drafter import OutreachDrafter, render_dry_run, draft_for_job
```

#### `OutreachDrafter(api_key, model="claude-sonnet-4-6")`
- `.draft(job, score, profile) -> str` — channel-aware (FT cover-letter or freelance pitch). Returns plain-text body, no subject. Hard rules baked into system prompts: no <2-week freelance, no hourly under €60/hr equivalent, no invented metrics.

#### `render_dry_run(job, score, profile) -> str`
Deterministic offline template — proves the prompt shape without burning tokens.

#### `draft_for_job(api_key, job, score, profile) -> tuple[str, str]`
Convenience: returns `(body, model_id)`.

---

### `career_os.tracker` — per-channel pipeline (Tier 3 Upgrade 11)

```python
from career_os.tracker import (
    FT_STAGES, FREELANCE_STAGES, TERMINAL, STAGES_BY_CHANNEL, ALL_STAGES,
    stages_for_channel, Application, StageTransitionError,
    record_application, advance, funnel_counts, flat_funnel_counts,
)
from career_os.tracker.pipeline import list_applications
```

#### Stage constants
- `FT_STAGES = ("drafted", "sent", "replied", "interview", "offer")`
- `FREELANCE_STAGES = ("drafted", "sent", "scope_call", "proposal_sent", "signed_proposal")`
- `TERMINAL = ("won", "rejected", "dropped")` — shared
- `STAGES_BY_CHANNEL: dict[str, tuple]` — keyed `ft` / `freelance` / `either` (either → FT)
- `ALL_STAGES` — deduped union, used as `click.Choice` source

#### `stages_for_channel(channel) -> tuple[str, ...]`
Full legal sequence (channel-specific + terminals). Unknown channel falls back to FT pipeline.

#### `Application` (frozen dataclass)
`job_key`, `stage`, `notes`, `channel`, `applied_at`, `updated_at`.

#### `record_application(store, job_key, stage="drafted", notes=None) -> Application`
Reads `job.channel` to populate `application.channel`. Raises `StageTransitionError` if the stage isn't legal for that channel.

#### `advance(store, job_key, to=None, notes=None) -> Application`
Walks the channel-specific tuple. `to=None` means "next stage in this application's pipeline". Cross-channel transitions raise.

#### `funnel_counts(store) -> dict[str, dict[str, int]]`
Nested per-channel counts: `{"ft": {stage: n, ...}, "freelance": {...}}`. Every channel pre-seeds its own stages to 0.

#### `flat_funnel_counts(store) -> dict[str, int]`
Sum across channels — only when you need a single combined view.

#### `list_applications(store, stage=None, channel=None) -> list[(Application, str)]`
Joined with `jobs.title`. Most-recently-updated first.

---

### `career_os.recheck` — stale-job detection (Tier 3 Upgrade 8)

```python
from career_os.recheck import recheck, summarize, RecheckOutcome, TRANSIENT_STRIKE_LIMIT
```

#### `await recheck(store, *, limit=200, max_age_days=7, source=None, concurrency=10) -> list[RecheckOutcome]`
Pull candidates, batch-check URLs, mark closures. Decisions:
- 404/410 → `closed` (reason `gone`)
- Redirect to `/jobs/`, `/closed`, `/expired` → `closed` (reason `redirected-to-listings`)
- Scraper's `is_closed(response)` returns True → `closed` (reason `source-marker`)
- 5xx, 4xx (other), network exceptions → `transient` + attempt bump
- `recheck_attempts >= TRANSIENT_STRIKE_LIMIT` (3) → `closed` (reason `unreachable`)

#### `RecheckOutcome` (frozen dataclass)
`job_key`, `decision` (`kept`/`closed`/`transient`), `reason`, `status_code`.

#### `summarize(outcomes) -> dict[str, int]`
Bucket counts for CLI display.

---

### `career_os.digest`

```python
from career_os.digest import render_digest, DigestEmailer, EmailResult
```

#### `render_digest(rows: list[(JobPost, Score)]) -> str`
Markdown body for CLI or email.

#### `DigestEmailer(provider, api_key, sender, recipient, subject_prefix="[Career-OS] ")`
Three backends:
- `resend` → `https://api.resend.com/emails` (Bearer)
- `postmark` → `https://api.postmarkapp.com/email` (`X-Postmark-Server-Token`)
- `gmail` → SMTP via `smtp.gmail.com:587` with app password

`.send(subject, markdown_body) -> EmailResult`. `EmailResult.ok` for success, `.detail` for body. Markdown is converted to minimal HTML for the multipart alternative.

---

### `career_os.eval`

```python
from career_os.eval import (
    evaluate_fixtures, evaluate_fixtures_with, summarize, load_fixtures, EvalRow,
)
```

#### `evaluate_fixtures(scorer, profile) -> list[EvalRow]`
Run live Claude scorer against `tests/fixtures/scored_jobs.jsonl`. Each row reports actual vs expected band + in-range bool.

#### `evaluate_fixtures_with(score_fn, profile) -> list[EvalRow]`
Same but takes any `(job, profile) -> Score` callable — used by the keyword-stub regression test.

#### `summarize(rows) -> dict`
`n`, `in_range`, `in_range_pct`, `mean_fit`, `median_fit`, `distribution_70_plus`, `distribution_30_to_55`.

#### `load_fixtures(path=FIXTURES_PATH) -> list[dict]`
Raw fixture loader. Skips `# ...` comment lines.

---

### `career_os.presence` — improve-post terminal spawner

```python
from career_os.presence import (
    prepare_session, spawn_improve_session, build_spawn_command,
    list_sessions, read_post_body, SpawnResult,
)
```

#### `prepare_session(post, root=None) -> Path`
Write `POST.md`, `ORIGINAL.md`, `CLAUDE.md` under `data/improve-sessions/post-<id>-<ts>/`. Returns the workdir.

#### `spawn_improve_session(post, env=None) -> SpawnResult`
End-to-end: prepare workdir, detect WSL vs Linux, spawn a new terminal running `claude` with an initial prompt. `.ok=False` + `.fallback_message` if no terminal found.

#### `build_spawn_command(workdir, env, initial_message=...) -> list[str] | None`
Pure: pick the right shell-spawn invocation. WSL → `cmd.exe /c start wt.exe wsl -- bash -c ...`. Linux tries gnome-terminal / konsole / x-terminal-emulator / xterm. Returns None when nothing is installed.

#### `read_post_body(workdir) -> str | None`
Pull the edited `POST.md` back out (strips frontmatter). Used by the dashboard's "Pull updates" button.

#### `list_sessions(post_id, root=None) -> list[Path]`
All workdirs for a post, newest first.

---

### `career_os.dashboard.queries` — read-side data for the UI

```python
from career_os.dashboard.queries import (
    source_health, top_matches, drafts_ready,
    funnel, flat_funnel, totals,
    SourceHealth, TopMatch, DraftReady,
)
```

#### `source_health(store) -> list[SourceHealth]`
Per-source rollup joined with `source_watermarks`. Includes sources with watermarks but no jobs yet (zombies). `SourceHealth` has `last_24h`, `last_7d`, `total`, `most_recent`, `last_status`, `last_fetched_at`, `closed_7d`, plus `.status_display` for the dashboard label.

#### `top_matches(store, limit=25, min_fit=60, channel=None) -> list[TopMatch]`
Closed jobs filtered out. `TopMatch` exposes parsed comp fields (`comp_min`, `comp_max`, `comp_currency`, `comp_period`) and `.comp_display` (formatted preferring parsed over raw).

#### `drafts_ready(store, limit=20) -> list[DraftReady]`
Drafted outreach that hasn't been added to the pipeline yet.

#### `funnel(store) -> dict[str, dict[str, int]]`
Per-channel funnel (re-exports `tracker.funnel_counts`).

#### `flat_funnel(store) -> dict[str, int]`
Back-compat single-funnel view across channels.

#### `totals(store) -> dict[str, int]`
`{"jobs": ..., "scored": ..., "drafts": ..., "applications": ...}`.

---

### `career_os.dashboard.ideas`

```python
from career_os.dashboard import ideas as ideas_lib
```

`Idea` (frozen dataclass): `id`, `title`, `hook`, `channel`, `tags`, `notes`, `archived`, `created_at`, `updated_at`.

| Function | Purpose |
|---|---|
| `add_idea(store, title, hook=None, channel="blog", tags=None, notes=None) -> Idea` | Insert. Validates channel ∈ `CHANNELS` and non-empty title. |
| `list_ideas(store, channel=None, include_archived=False) -> list[Idea]` | Most-recently-updated first. |
| `update_idea(store, idea_id, *, title=None, hook=None, channel=None, tags=None, notes=None) -> Idea` | Partial update. |
| `archive(store, idea_id, archived=True) -> Idea` | Toggle archive. |
| `delete_idea(store, idea_id) -> bool` | Hard delete. |
| `counts_by_channel(store) -> dict[str, int]` | Active-only per-channel counts. |

`CHANNELS = ("blog", "linkedin", "x", "devto", "medium", "hn")`.

---

### `career_os.dashboard.posts`

```python
from career_os.dashboard import posts as posts_lib
```

`Post` (frozen dataclass): `id`, `title`, `channel`, `status`, `body`, `notes`, `created_at`, `updated_at`, `posted_at`.

| Function | Purpose |
|---|---|
| `add_post(store, title, channel="blog", body="", notes=None) -> Post` | Create (status defaults to `drafting`). |
| `list_posts(store, status=None, channel=None) -> list[Post]` | Most-recently-updated first. |
| `update_post(store, post_id, *, title=None, channel=None, body=None, notes=None) -> Post` | Partial update. |
| `set_status(store, post_id, status) -> Post` | Move drafting → ready → posted. Stamps `posted_at` on `posted`. |
| `delete_post(store, post_id) -> bool` | Hard delete. |
| `get_post(store, post_id) -> Post \| None` | Single lookup. |
| `counts_by_status(store) -> dict[str, int]` | Status totals for the page header. |

`CHANNELS = ("blog", "linkedin", "x", "devto", "medium", "hn")`. `STATUSES = ("drafting", "ready", "posted")`.

---

### `career_os.dashboard.todos`

```python
from career_os.dashboard import todos as todos_lib
```

`Todo` (frozen dataclass) with `.is_overdue`, `.days_until_due`.

| Function | Purpose |
|---|---|
| `seed_default_plan(store) -> {"inserted", "untouched"}` | Insert seeds from `plan.py` without clobbering existing rows. |
| `sync_plan(store) -> {"inserted", "updated", "removed"}` | Full reconcile: insert new, update priorities/dates, remove orphan seeds. Ad-hoc rows untouched. |
| `count_orphan_seeds(store) -> int` | Seeded rows that no longer exist in `DEFAULT_PLAN` — banner trigger. |
| `list_todos(store, section=None, open_only=False, priority=None, query=None) -> list[Todo]` | Filtered list. |
| `toggle(store, todo_id, checked) -> Todo` | Check/uncheck. |
| `update_notes(store, todo_id, notes) -> Todo` | Save notes popover content. |
| `add_custom(store, section, item, priority="P1", due_date=None, notes=None) -> Todo` | Add an ad-hoc (non-seed) row. |
| `delete_todo(store, todo_id) -> bool` | Delete an ad-hoc row. Seeds are deleted via `sync_plan`. |
| `section_progress(store) -> dict[str, {"done": int, "total": int}]` | Per-section progress, canonical order preserved. |
| `overall_progress(store) -> (done, total)` | Grand totals. |
| `todays_focus(store, horizon_days=7, limit=8) -> list[Todo]` | P0 items due within horizon. |

---

### `career_os.dashboard.network`

```python
from career_os.dashboard.network import (
    detect_environment, build_reachable_urls, render_diagnostics, Environment,
)
```

| Function | Purpose |
|---|---|
| `detect_environment() -> Environment` | Sniff `/proc/version`, hostname, primary IP. |
| `build_reachable_urls(env, address, port) -> list[(label, url)]` | Localhost + LAN/WSL IP variants in preferred-try order. |
| `render_diagnostics(env, port) -> str` | Long-form WSL networking recipes for `career-os dashboard --diagnose`. |

`Environment` (frozen): `is_wsl`, `is_docker`, `primary_ip`, `hostname`.

---

## 3. Configuration / env vars

Loaded by `Settings.load()` from `.env` at the repo root.

| Var | Purpose | Required for |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API auth | `score`, `draft`, `eval` (live), watch-list AI features |
| `DATABASE_URL` | SQLite path. Default `sqlite:///data/career_os.db`. Postgres pending. | always |
| `SMTP_PROVIDER` | `resend` \| `postmark` \| `gmail` | `digest --send` |
| `SMTP_API_KEY` | Provider API key / Gmail app password | `digest --send` |
| `SMTP_FROM` | Sender address | `digest --send` |
| `SMTP_TO` | Recipient address | `digest --send` |

LinkedIn cookie vars (`LINKEDIN_LI_AT`, `LINKEDIN_JSESSIONID`, `LINKEDIN_BCOOKIE`) and `CAREER_OS_HOST=vps` (residential-IP gate) are reserved for Tier 2 Upgrade 5 (browser scrapers) — not used yet.

---

## 4. Database schema (concise)

SQLite tables created via `CREATE TABLE IF NOT EXISTS` on Store init.
Column additions handled by `db/migrations.py`.

| Table | Purpose |
|---|---|
| `jobs` | One row per posting. Tier 1 added `comp_min`/`comp_max`/`comp_currency`/`comp_period`. Tier 3 added `is_closed`/`closed_at`/`last_rechecked_at`/`recheck_attempts`. |
| `scores` | Per-job fit (0-100) + reasoning + pros/cons + suggested angle. |
| `applications` | Pipeline tracker. Tier 3 added `channel` (`ft` / `freelance` / `either`). |
| `drafts` | Generated outreach bodies. |
| `todos` | Seeded 12-week plan + ad-hoc items. |
| `ideas` | Raw content jottings (blog/LinkedIn/X/dev.to/Medium/HN). |
| `posts` | Drafts being shaped toward publish. Independent from ideas. |
| `source_watermarks` | Per-source incremental-fetch state (Tier 2). Composite keys for sub-feeds (e.g. `weworkremotely:programming`). |

Foreign keys cascade on delete from `jobs` for `scores` / `applications` / `drafts`.

---

## 5. Skills (for working WITH this codebase)

Project-scope under `.claude/skills/`:

- **add-scraper** — Scraper subclass + registry wiring + respx test recipe. Highest-leverage skill given the EU-board backlog.
- **add-dashboard-page** — `pages/<name>.py` + `st.Page` nav + UI-free data module + AppTest fixture.

Invoke either with `/add-scraper` or `/add-dashboard-page` from the Claude
Code CLI when you're adding that kind of feature.

---

## 6. Quick recipes

### Score 50 unscored jobs, render today's digest

```python
from career_os.config import Settings
from career_os.db import Store
from career_os.scorer import ClaudeScorer, score_pending
from career_os.profile import DEFAULT_PROFILE
from career_os.digest import render_digest

settings = Settings.load()
store = Store(settings.database_url)
score_pending(store, ClaudeScorer(settings.anthropic_api_key), DEFAULT_PROFILE, limit=50)
print(render_digest(store.top_scored(limit=5, min_fit=70)))
```

### Apply to a freelance gig and walk it forward

```python
from career_os.tracker import record_application, advance

record_application(store, "hn_freelancer:42")  # → drafted
advance(store, "hn_freelancer:42")              # → sent
advance(store, "hn_freelancer:42")              # → scope_call
advance(store, "hn_freelancer:42", to="won")    # → won (terminal)
```

### Recheck weekly to prune dead links

```python
import asyncio
from career_os.recheck import recheck, summarize

outcomes = asyncio.run(recheck(store, limit=500, max_age_days=7))
print(summarize(outcomes))
# {'kept': 412, 'closed': 67, 'transient': 21}
```

### Parse a freelance budget and check the floor

```python
from career_os.salary import parse

comp = parse("€40/hr")
if (eur := comp.to_eur_hourly()) is not None and eur < 60:
    print(f"Below floor: {eur:.0f} EUR/hr")
```

### Spawn Claude on a post draft

```python
from career_os.dashboard import posts as posts_lib
from career_os.presence import spawn_improve_session

post = posts_lib.get_post(store, post_id=3)
result = spawn_improve_session(post)
print(result.workdir)  # data/improve-sessions/post-3-<ts>/
```
