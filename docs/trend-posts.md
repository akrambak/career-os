# Trend-driven post generator — schema + strategy

**Goal:** AI-generated posts for X / LinkedIn / dev.to / blog, anchored
in *real* current trends — not generic AI fluff. Trends are scraped from
public sources, scored by signal, and used as the seed for Claude-drafted
posts that the user reviews + ships.

This is the bridge between the existing reputation infrastructure (Posts
page, Inbox, Automations, KPIs) and the daily question "what should I
post about today?"

---

## Why "real" trends matter

The user's positioning is "8y production fullstack now layering Claude SDK
on top." Posts that ride a real wave (new model release, framework
breakage, recent CVE, viral HN discussion) outperform evergreen posts
**5-10×** on impressions and signal-bearing engagement (comments + DMs vs.
likes). Generic "5 lessons I learned about AI" posts compound nothing.

The system has to pull *fresh* signals — not seeded keyword lists — and
the user has to *review* every draft before it ships. That's the HITL
boundary.

---

## Architecture overview

```
                                   ┌────────────────────┐
   trend sources                   │ scrapers           │
   ──────────────                  │  hn (Algolia)      │
   HN frontpage              ────► │  devto (top-of-wk) │ ────┐
   dev.to top                      │  tavily (web srch) │     │
   reddit r/programming            │  reddit (rss)      │     │
   Tavily web search               └────────────────────┘     │
                                                              ▼
                                         ┌───────────────────────────┐
                                         │ trends (table)            │
                                         │  ↳ signal_score (decayed) │
                                         └─────────────┬─────────────┘
                                                       │
                                ┌──────────────────────┴─────────────────┐
                                │                                        │
                                ▼                                        ▼
                       ┌─────────────────┐                      ┌──────────────────┐
                       │ Trends page UI  │                      │ post generator   │
                       │  (review feed)  │ ──user clicks──────► │  (Claude per-ch) │
                       └─────────────────┘                      └──────────┬───────┘
                                                                           │
                                                                           ▼
                                                                  ┌──────────────────┐
                                                                  │ posts (table)    │
                                                                  │  status=drafting │
                                                                  │  trend_id=X      │
                                                                  └──────────┬───────┘
                                                                             │
                                                                             ▼
                                                                    Inbox: review_post
                                                                             │
                                                                             ▼
                                                                       User ships
```

Every box exists today *except* the trend sources, signal-scoring, the
generator, and the page. This doc covers those four pieces.

---

## Schema

### New table — `trends`

```sql
CREATE TABLE IF NOT EXISTS trends (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,         -- hn | devto | reddit | tavily | manual
    external_id   TEXT,                  -- HN story id, devto article id, etc.
    url           TEXT NOT NULL,
    title         TEXT NOT NULL,
    summary       TEXT,                  -- auto- or LLM-derived
    score         INTEGER NOT NULL DEFAULT 0,   -- HN points / devto reactions / stars
    comment_count INTEGER NOT NULL DEFAULT 0,
    tags          TEXT NOT NULL DEFAULT '[]',   -- JSON array
    raw           TEXT NOT NULL DEFAULT '{}',   -- JSON: source-specific payload
    signal_score  REAL NOT NULL DEFAULT 0,      -- computed; see formula below
    fetched_at    TEXT NOT NULL,
    used_at       TEXT,                          -- set when a post is generated
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_trends_signal ON trends(signal_score DESC);
CREATE INDEX IF NOT EXISTS idx_trends_source ON trends(source);
CREATE INDEX IF NOT EXISTS idx_trends_fetched ON trends(fetched_at);
```

**Design notes:**

- `UNIQUE(source, external_id)` — dedup. Re-scans never create duplicate
  rows; they update `score`, `comment_count`, and re-compute `signal_score`
  via upsert.
- `raw` JSON blob — keeps source-specific fields (HN author, devto cover
  image, Tavily snippet) so we never lose data we might want later without
  re-scraping.
- `used_at` — non-null means the user generated at least one post from
  this trend. The Trends page de-prioritizes used trends so the feed
  stays fresh.
- `manual` source — the user can paste a trend by hand from the UI; same
  schema, source='manual'.

### Migration — link `posts` back to `trends`

```sql
ALTER TABLE posts ADD COLUMN trend_id INTEGER REFERENCES trends(id);
CREATE INDEX IF NOT EXISTS idx_posts_trend_id ON posts(trend_id);
```

Nullable on purpose — human-written posts (no AI generator) leave it NULL.

---

## Trend sources

Lean MVP — three sources, ranked by signal density:

| Source | API | Auth | Why | Per-fetch cost |
|---|---|---|---|---|
| **HN frontpage** | `hn.algolia.com/api/v1/search?tags=front_page` | none | Highest signal for dev/AI/infra in EN. Comments reveal *what people actually disagree about* — the gold for posts. | free |
| **dev.to top-of-week** | `dev.to/api/articles?top=7` | none | Pure dev community; tags align with user's stack (Laravel, Vue, Python, Claude). | free |
| **Tavily web search** | `api.tavily.com/search` | optional `TAVILY_API_KEY` | Catches off-platform trends (twitter discourse, model releases, vendor blog posts). Use when set. | cheap (~$0.005/search) |

Deferred for later:
- **Reddit** — RSS works but signal-to-noise is lower than HN for our purposes.
- **GitHub trending** — useful for "trending repos this week" posts; scrape later.
- **X/Twitter** — no public API at our spend tier; manual entry via `source='manual'`.

### HN scraper detail

Algolia search returns the current frontpage stories:

```
GET https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=50
```

Each hit has `objectID`, `title`, `url`, `points`, `num_comments`,
`created_at_i`, `author`. We upsert one row per hit. `external_id =
objectID`. Re-running 5 minutes later updates points/comments and
recomputes signal_score.

### dev.to scraper detail

```
GET https://dev.to/api/articles?top=7
```

Returns 30 top-of-week articles. Each has `id`, `title`, `url`,
`positive_reactions_count`, `comments_count`, `tag_list`, `description`.
`external_id = id`. Tags align with the user's stack — perfect for topic
matching.

### Tavily web search detail

When `TAVILY_API_KEY` is set, run two periodic queries:

1. `"latest AI / LLM news this week"` → general AI pulse
2. Per-domain: `"trending PHP Laravel"`, `"new Claude SDK features"`,
   etc. — keyed off the user's `Profile.proven_stack` + `new_stack`.

Tavily returns a short list of `{title, url, content, score}` results.
External_id = SHA1(url) for stability across runs.

---

## Signal-score formula

A scalar 0..∞ that ranks trends for the Trends page and the post
generator. Three factors multiplied:

```
signal_score = base_score × recency_factor × topic_factor
```

| Factor | Definition | Range |
|---|---|---|
| `base_score` | log10(1 + score) + 0.5 × log10(1 + comments). Log-compresses to avoid one viral story dominating. | 0..~4 |
| `recency_factor` | linear decay over 168 hours. Fresh = 1.0, 7-day-old = 0.0. | 0..1 |
| `topic_factor` | 1.0 baseline + 0.3 per matched profile term in title+tags. Caps at 2.0. | 1..2 |

A trend with 500 HN points and 200 comments posted 12h ago, mentioning
"Claude" (user's `new_stack`): `(log10(501) + 0.5×log10(201)) × ~0.93 × 1.3 = ~4.6`.

A trend with 50 HN points, 5 comments, 5 days old, no profile match:
`(log10(51) + 0.5×log10(6)) × 0.29 × 1.0 = ~0.6`.

**Re-compute on every upsert** so a story climbing the frontpage rises in
our feed within the same minute we re-scan.

---

## Post generator

### Claude prompts (per channel)

Four channel-specific system prompts. Each lives at
`presence/prompts/generate_post_<channel>.md` so the user can edit copy
without code changes (mirrors `presence/prompts/improve_post.md`).

| Channel | Word target | Tone | CTA |
|---|---|---|---|
| **x** | 180-280 chars OR 3-5 tweet thread | terse, opinion-led, one specific take | reply with your take |
| **linkedin** | 180-280 words | first-person builder voice, one specific insight, hook in line 1 | comment / DM (link in first comment) |
| **devto** | 600-900 words | technical with code blocks, TL;DR, canonical_url to bak-dev.com | comment |
| **blog** | 800-1500 words | full essay, lead/middle/close | implicit (the URL is the destination) |

### Generator signature

```python
def generate_post(
    api_key: str,
    trend: Trend,
    channel: str,            # 'x' | 'linkedin' | 'devto' | 'blog'
    profile: Profile,
) -> tuple[str, str]:        # (body, model_id)
```

Hard rules baked into every prompt (matches `outreach.py`):

- Never invent metrics, employers, or links beyond what's in the trend.
- Senior signal up front (8y production, e-commerce + AI agents) without
  being a humble-brag.
- Real-name builder voice — no third-person remove, no "I'm passionate
  about...".
- If the trend is bad fit (off-topic for the user's positioning), refuse:
  return a marker like `[NO-FIT: <reason>]` so the dashboard can skip
  saving and surface the reason.

### Dry-run mode

Identical to `drafter/outreach.py`: a template-based fallback that proves
the prompt shape without burning Claude tokens. Used in tests + when
`ANTHROPIC_API_KEY` is not set.

---

## HITL flow

1. **Scrape** — automation `scan_trends_daily` runs every 4h, refreshes
   `trends` table.
2. **Detect** — action generator `gen_high_signal_trends` emits a
   `review_trend` Inbox action for any trend whose signal_score crosses a
   threshold AND `used_at IS NULL`.
3. **Click** — user clicks the Inbox action OR opens the Trends page
   directly.
4. **Generate** — user clicks "Generate post → LinkedIn" on a trend.
   Claude drafts. The draft lands in `posts` with `trend_id` set and
   `status='drafting'`.
5. **Inbox surfaces ready posts** — when user advances the post to
   `status='ready'`, `gen_publish_ready_posts` (already wired) emits a
   `review_post` action.
6. **Ship** — user reviews one more time, publishes (manual today;
   future Phase 3 cross-poster), advances to `status='posted'`.

The human is in the loop at THREE points:
- Approve the trend as worth posting about (Inbox → Trends page).
- Approve the AI-drafted body (Posts page, edit or "Improve with Claude").
- Approve the publish (Posts page → set_status('posted')).

No autonomous publishing. Ever.

---

## Automation cadence

Two new entries in `automations.DEFAULT_AUTOMATIONS`:

```python
("scan_trends_4h", "scan_trends", 60 * 4,
 {"sources": ["hn", "devto"]}, True),
("trend_actions_hourly", "trend_action_generators", 60,
 {"signal_threshold": 2.5}, True),
```

`scan_trends` handler:
- Async call into the three scrapers.
- Returns `HandlerResult("ok", "<N> new trends · <M> updated")`.
- Skipped if no `TAVILY_API_KEY` (only HN+devto run).

`trend_action_generators` handler:
- Runs `gen_high_signal_trends` and `gen_review_post` (post-status='ready'
  detector — already shipped in Pillar 1).
- Idempotent via `actions.upsert_action` UNIQUE constraint.

---

## Dashboard page — `Trends`

Position in nav: between **Posts** and **KPIs** (right after the
content-pipeline pages).

Layout:

```
┌──────────────────────────────────────────────────────────────────┐
│ Trends                                                           │
│ Real-time signal from HN, dev.to, web search. Click a trend to   │
│ generate a draft post; review on the Posts page.                 │
├──────────────────────────────────────────────────────────────────┤
│ Sidebar:                                                         │
│  • [🔍 Scan now]   (fires scan_trends automation manually)       │
│  • Source filter   (hn | devto | tavily | all)                   │
│  • Min signal      (slider 0..5, default 1.5)                    │
│  • Hide used       (default: on)                                 │
├──────────────────────────────────────────────────────────────────┤
│ Feed:                                                            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ [3.4]  📰 hn   Anthropic releases tool-streaming API       │  │
│  │ 12h ago · 420 points · 187 comments · Claude, sdk          │  │
│  │ [open ↗] [Generate → X] [→ LinkedIn] [→ devto] [→ blog]    │  │
│  │ used: ✓ 1 post (2026-05-19)  (collapsible)                 │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  (...sorted by signal_score desc, paginated)                     │
└──────────────────────────────────────────────────────────────────┘
```

Per-trend buttons spawn the generator inline. While it runs, show a
spinner; on success, toast "Draft created on Posts page" + a link.

---

## Files to add

```
src/career_os/trends/
    __init__.py            # Trend dataclass + CRUD + signal score
    sources.py             # HN + devto + Tavily scrapers
    generator.py           # Claude per-channel prompts + dry-run
src/career_os/dashboard/pages/
    trends.py              # the page
presence/prompts/
    generate_post_x.md
    generate_post_linkedin.md
    generate_post_devto.md
    generate_post_blog.md
tests/
    test_trends.py
    test_trend_sources.py
    test_trend_generator.py
    test_dashboard_trends.py
```

Modifications:
- `db/store.py` SCHEMA — add `trends` table.
- `db/migrations.py` — add `posts.trend_id`.
- `dashboard/app.py` — register Trends page in PAGES.
- `automations/__init__.py` — register `scan_trends` + `trend_action_generators` handlers + default rows.
- `actions/__init__.py` — add `gen_high_signal_trends`.
- `cli/main.py` — new `career-os trends scan` command (idempotent, dry-run-aware).
- `.env.example` — add `TAVILY_API_KEY` line (optional).

---

## What we DO NOT build (yet)

- **Auto-publish.** No automation writes to dev.to / LinkedIn / X. The
  user is the publisher.
- **Cross-poster.** Already deferred — Phase 3 of the master plan. The
  Posts page is the boundary today (clipboard / manual paste).
- **NER on trend content.** No entity extraction. The signal-score
  formula uses keyword matching against the profile, which is good
  enough.
- **Engagement tracking back to the trend.** Phase 3 too — once we have
  posted_at on posts and impressions/likes ingestion.

---

## Open questions

1. **Tavily search queries** — hard-code the 3-5 queries in
   `trends/sources.py`, or pull them from `Profile.proven_stack` /
   `new_stack` on each run? Defaulting to derived-from-profile so the
   queries auto-track positioning shifts.
2. **Default signal threshold** for Inbox actions — 2.5 (calibrated on
   sample data) feels right but needs a week of real fetches to validate.
   Surface it as a config knob on the `trend_actions_hourly` automation.
3. **Refresh interval** — 4h on scan_trends. HN frontpage shifts faster
   than that; consider 2h once we see how much Tavily costs add up.
4. **Topic-factor caps** — the 2.0 cap on `topic_factor` keeps a
   100%-stack-match trend from drowning out a higher-engagement
   adjacent-topic one. May need tuning after seeing real data.

These don't block shipping the MVP — they're tuning knobs.
