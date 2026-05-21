# SEO link-building strategy — 3 features for Career-OS

**Goal:** turn the build-in-public surface (bak-dev.com, github.com/akrambak/
career-os, dev.to posts, LinkedIn/X presence) into a compounding backlink
graph that signals authority to Google AND drives organic traffic from
referring sites. Today the dashboard tracks content and pipelines but is
blind to who's actually linking to the user.

Three features, each operationally cheap and tightly integrated with the
HITL Inbox, Automations, and Actions infrastructure that already exists.

---

## Senior-advisor framing

Backlink strategy at the indie-dev level has three pillars. **Most
people only think about #2.** That's why most efforts plateau.

1. **Inventory & hygiene** — Know what links you have. Know which ones
   die. Know your anchor-text distribution (over-optimization = penalty).
   Without this, you can't measure anything else.
2. **Acquisition** — Pursue new links via outreach (guest posts, podcasts,
   directory submissions, HARO replies, tool roundups). This is the
   action-driven part most blogs talk about.
3. **Conversion** — Find unlinked mentions and convert them to links.
   The cheapest, highest-ROI work — someone already wrote about you;
   asking for a link added is a 10-min task with a 60%+ success rate
   for cold-but-relevant requests.

The 3 features map 1:1 to these pillars.

---

## Feature 1 — Backlinks Inventory + Health

### Why this is foundational

You can't track conversion rate from outreach without knowing whether
the published link is still live. You can't detect anchor-over-
optimization without per-link anchors. You can't celebrate wins without
a list of wins. **This is the table everything else joins to.**

### Schema

```sql
CREATE TABLE IF NOT EXISTS backlinks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source_url        TEXT NOT NULL,        -- the page linking TO us
    source_domain     TEXT NOT NULL,        -- parsed root domain, indexed
    target_url        TEXT NOT NULL,        -- our URL being linked to
    anchor_text       TEXT,                 -- the visible link text
    rel              TEXT NOT NULL DEFAULT 'dofollow',
                                            -- dofollow | nofollow | ugc | sponsored
    status            TEXT NOT NULL DEFAULT 'live',
                                            -- live | dead | redirect | removed | unverified
    da_estimate       INTEGER,              -- 0-100 manual / future API
    discovered_via    TEXT NOT NULL,        -- manual | mention_hunter | gsc | gh_search
    first_seen_at     TEXT NOT NULL,
    last_checked_at   TEXT,
    recheck_attempts  INTEGER NOT NULL DEFAULT 0,
    notes             TEXT,
    UNIQUE(source_url, target_url)
);

CREATE INDEX IF NOT EXISTS idx_backlinks_source_domain ON backlinks(source_domain);
CREATE INDEX IF NOT EXISTS idx_backlinks_status ON backlinks(status);
CREATE INDEX IF NOT EXISTS idx_backlinks_rel ON backlinks(rel);
CREATE INDEX IF NOT EXISTS idx_backlinks_last_checked ON backlinks(last_checked_at);
```

**`UNIQUE(source_url, target_url)`** — one row per (source page, target
page). Re-discovery refreshes anchor + status, doesn't duplicate.

### Health-check loop (reuses Tier 3 Upgrade 8 pattern)

`career-os backlinks-recheck` issues a GET against each `source_url`.
The page body is searched for the target URL (or canonical-form variant).
Decisions:

| Source response | Body contains target URL? | Decision |
|---|---|---|
| 200 | yes | `status=live`, increment `last_checked_at`, reset attempts |
| 200 | no  | `status=removed` (page exists but our link is gone) |
| 301/302 | (follow) | `status=redirect`, log final URL in notes |
| 404/410 | n/a | `status=dead` |
| 5xx / timeout | n/a | bump `recheck_attempts`; 3 strikes → `status=dead` (reason `unreachable`) |

A `rel=...` scan during the body parse re-classifies the link (a once-
dofollow link going nofollow is a signal to investigate).

### Automation row

```python
("backlinks_recheck_weekly", "backlinks_recheck", 60 * 24 * 7,
 {"limit": 200}, False)
```

Disarmed by default (the user opts in when there's > 0 links to check).

### Action generator: `gen_dead_backlinks`

For each row that flipped `live → dead/removed` since the last
generator run, emit a `dead_backlink` action in the Inbox. Severity:
`urgent` for backlinks on referring domains with `da_estimate >= 40`;
`normal` otherwise. The user reaches out to the publisher (or finds
the new URL) to recover.

### Dashboard page — `Backlinks`

Layout:
- **Header**: 4 metrics — total live · total dead · dofollow ratio ·
  unique referring domains
- **Filters sidebar**: status / rel / min DA / "discovered via"
- **Recheck-now button** (manual fire of the weekly automation)
- **Add-by-hand form** (paste source URL + target URL + anchor)
- **Table**: source_url · anchor · target · rel badge · status badge ·
  DA · last_checked. Click row → expand to notes + recheck-attempts +
  one-click "fetch fresh" button.

---

## Feature 2 — Outreach Targets Pipeline

### Why this is the action engine

The Career-OS dashboard already excels at HITL pipelines (job
applications, post drafts). Linking is identical in shape: a queue of
opportunities, a stage machine, a Claude-drafted pitch, a notes field
for follow-ups. Reuse the pattern — don't reinvent.

### Schema

```sql
CREATE TABLE IF NOT EXISTS outreach_targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,            -- "Smashing Magazine guest post"
    site_url        TEXT NOT NULL,
    site_domain     TEXT NOT NULL,
    category        TEXT NOT NULL,            -- podcast | guest_post |
                                              -- directory | haro |
                                              -- roundup | community |
                                              -- newsletter | unlinked_mention
    contact         TEXT,                     -- email, twitter handle, form URL
    pitch_angle     TEXT,                     -- one-line: how WE fit this target
    stage           TEXT NOT NULL DEFAULT 'researching',
                                              -- researching | pitched | replied |
                                              -- accepted | published | declined |
                                              -- dropped
    value_score     INTEGER NOT NULL DEFAULT 5,  -- 1-10 prioritization
    da_estimate     INTEGER,
    target_backlink_url TEXT,                  -- the page we expect to be linked from
    pitch_draft     TEXT,                      -- Claude-generated body
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    pitched_at      TEXT,
    published_at    TEXT,
    UNIQUE(site_url, category)
);

CREATE INDEX IF NOT EXISTS idx_outreach_targets_stage ON outreach_targets(stage);
CREATE INDEX IF NOT EXISTS idx_outreach_targets_category ON outreach_targets(category);
CREATE INDEX IF NOT EXISTS idx_outreach_targets_updated ON outreach_targets(updated_at);
```

### Stage machine

```
researching → pitched → replied → accepted → published → (linked!)
                ↘            ↘
              declined      dropped
```

Mirrors `tracker/pipeline.py` shape. Terminal stages: `published`,
`declined`, `dropped`. Cross-category (a podcast pitch isn't an HARO
reply) — but pitch templates differ by category, not stage.

### Per-category Claude pitch prompts

One file per category under `presence/prompts/pitch_<category>.md`,
mirrors the post-generator prompt structure:

- `pitch_guest_post.md` — pitches a guest post with a 3-line angle,
  one production-grade hook, sample headline, links to 2 prior posts.
- `pitch_podcast.md` — short cold-email asking to guest on the show;
  references one episode + ties the user's expertise to it.
- `pitch_directory.md` — submission copy for a tools directory listing.
- `pitch_haro.md` — direct journalist reply per HARO rules: lead with
  credentials, 3-sentence answer, byline link.
- `pitch_roundup.md` — fits the user's piece into an existing "top X"
  roundup post.
- `pitch_unlinked_mention.md` — short, friendly ask to convert an
  existing mention to a linked one. (Cross-feature with Mention Hunter.)

Generator: `outreach/generator.py:generate_pitch(target, profile)` —
loads the right prompt, returns a draft. Reuses the dry-run template
fallback pattern from the existing drafter.

### Stale-pitch action generator

`gen_stale_outreach`: any target with `stage='pitched'` and
`pitched_at` older than 10 days → `stale_pitch` Inbox action. Push
the user to follow up or mark `declined`/`dropped`.

### Dashboard page — `Outreach`

Layout:
- **Header**: per-category funnel (researching → published) — matches
  the per-channel pipeline render style already on Overview.
- **Filters**: category / stage / min value_score
- **Add-target form**: name, site URL, category, value_score, pitch angle
- **Target list**: per-row stage chip, value_score, category badge.
  Each row has a "Generate pitch" button (Claude) and "Advance stage" /
  "Mark declined" / "Mark published".

### Automation

```python
("stale_outreach_actions_daily", "outreach_stale_actions", 60 * 24,
 {"days": 10}, True)
```

Pure action-generator fire — no scraping, just looks at the table.

---

## Feature 3 — Mention Hunter

### Why this is the highest-ROI pillar

You're already getting mentioned. Half those mentions aren't links.
Converting 30% of them is faster than starting cold pitches from
scratch. **This is where new-user link-building accelerates fastest.**

### Schema

```sql
CREATE TABLE IF NOT EXISTS mentions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,            -- hn | devto | github | reddit | tavily | manual
    source_url      TEXT NOT NULL,
    matched_term    TEXT NOT NULL,            -- "bak-dev.com" | "akrambak/career-os" | "AkBak"
    context_snippet TEXT,                     -- ~280 char excerpt around the match
    has_link        INTEGER NOT NULL DEFAULT 0,
                                              -- 1 = already linked (cross-check vs backlinks)
                                              -- 0 = unlinked → convert to backlink
    status          TEXT NOT NULL DEFAULT 'open',
                                              -- open | converted | dismissed | linked
    discovered_at   TEXT NOT NULL,
    notes           TEXT,
    UNIQUE(source_url, matched_term)
);

CREATE INDEX IF NOT EXISTS idx_mentions_status ON mentions(status);
CREATE INDEX IF NOT EXISTS idx_mentions_has_link ON mentions(has_link);
CREATE INDEX IF NOT EXISTS idx_mentions_source ON mentions(source);
```

### Discovery sources

Lean MVP — three sources matching the trend-scraper pattern:

| Source | API | Why |
|---|---|---|
| **HN search by content** | `hn.algolia.com/api/v1/search?query=<term>&tags=comment,story` | Catches every comment + story mentioning the user's URLs. Free. |
| **dev.to** | `dev.to/api/articles/search?q=<term>` + body scrape | Articles citing the user's blog posts or repo. Free. |
| **GitHub code search** | `api.github.com/search/code?q=<term>` | README references + code references to the user's repo. Needs a token (PAT) but rate-limit is generous. |

Search terms are derived from a small static config: the user's
domains + handles + repo identifiers. Adding a new term is a 1-line
edit.

### `has_link` detection

For HN / dev.to / GitHub, the API returns a body or excerpt. We
substring-match the user's URLs:

- "bak-dev.com" present anywhere → `has_link=1` (we assume the URL
  itself is the link; even if it's plain-text in the body, it's still
  a discoverable reference and may have been auto-linked by the
  platform's renderer)
- The user's brand-name ("AkBak", "Bakhouche Akram") present but no
  URL → `has_link=0` → high-value unlinked mention

A second pass (optional, slower) fetches the source URL and parses
the rendered HTML for an actual `<a href>` to the user's domain. Not
in the MVP — start with content-substring as a heuristic, refine if
false positive rate is high.

### Cross-feature wiring

- **→ Backlinks**: when an unlinked mention is "converted" (the user
  reached out, publisher added the link), the dashboard's "Convert to
  backlink" button creates a `backlinks` row pre-filled with
  source_url + target_url, sets `mentions.status='converted'`.
- **→ Outreach**: a "Pitch to convert" button on an unlinked mention
  creates an `outreach_targets` row with `category='unlinked_mention'`,
  pulls the source_url into `site_url`, and lands on the Outreach page
  in `stage='researching'` ready for the user to pick a pitch angle.

### Automation

```python
("mention_scan_daily", "mention_scan", 60 * 24,
 {"sources": ["hn", "devto"]}, True)
```

(GitHub disabled by default because it requires a `GITHUB_TOKEN`.)

### Action generator: `gen_unlinked_mentions`

For each new `mentions` row with `has_link=0` and `status='open'`,
emit an `unlinked_mention` Inbox action. Severity `normal` (urgent
only for high-DA sources, configured per-source).

### Dashboard page — `Mentions`

Layout:
- **Header**: 3 metrics — unlinked / linked / converted
- **Filters**: source / status / has_link
- **Per-mention row**: source badge, snippet, "Convert to backlink",
  "Pitch to convert" (→ Outreach), "Dismiss"
- **Add-by-hand form** for manual entry of mentions the user found
  through Twitter/Slack/etc. that wouldn't show up in automated scans.

---

## Wiring summary (what changes across the codebase)

### New tables (in `db/store.py` SCHEMA)
- `backlinks`, `outreach_targets`, `mentions`

### New modules
```
src/career_os/backlinks/
    __init__.py            # Backlink dataclass + CRUD + health-check driver
src/career_os/outreach/
    __init__.py            # OutreachTarget dataclass + state machine + CRUD
    generator.py           # Per-category Claude pitch generator
src/career_os/mentions/
    __init__.py            # Mention dataclass + CRUD + cross-feature converters
    sources.py             # HN / devto / GH scrapers
```

### New presence prompts
```
presence/prompts/
    pitch_guest_post.md
    pitch_podcast.md
    pitch_directory.md
    pitch_haro.md
    pitch_roundup.md
    pitch_unlinked_mention.md
```

### New dashboard pages
```
src/career_os/dashboard/pages/
    backlinks.py
    outreach.py
    mentions.py
```

Navigation order (post-update): Overview · Inbox · Automations ·
To-Do · Ideas · Posts · Trends · **Backlinks · Outreach · Mentions** ·
KPIs.

### New CLI commands
```
career-os backlinks-recheck [--limit 200]
career-os outreach-list [--stage STAGE] [--category CAT]
career-os mentions-scan [--source KEY]
```

### Action kinds (added to Inbox)
- `dead_backlink` (live → dead/removed detection)
- `stale_pitch` (10-day-stale outreach)
- `unlinked_mention` (new unlinked mention discovered)
- `backlink_won` (a stage transition `pitched → published` on an
  outreach target) — optional, a "celebrate the win" Inbox row

### Automation handlers
- `backlinks_recheck` (weekly)
- `mention_scan` (daily)
- `outreach_stale_actions` (daily — pure inbox generator, no I/O)

### KPI additions (Pillar 3 KPIs page)
Add three KPIs to the existing registry:
- `backlinks_live` (derived, gte 50 by Aug 8) — Tier 1
- `dofollow_ratio` (derived, gte 0.6) — Tier 1
- `outreach_pitched_wk` (derived, gte 5) — Tier 2

---

## Implementation order

```
1. Strategy doc (this file)
2. Feature 1 — Backlinks foundation:
     schema · module · page · recheck CLI + automation · dead-backlink action
3. Feature 2 — Outreach pipeline:
     schema · module + state machine · pitch generator · page ·
     stale-pitch action · per-category Claude prompts
4. Feature 3 — Mention Hunter:
     schema · module · scrapers · page · unlinked-mention action ·
     convert-to-backlink + pitch-to-convert cross-feature buttons
5. KPI registry extensions (3 new derived KPIs)
6. Tests, ruff, multi-commit, push
```

Each feature is an isolated shipping unit. Feature 1 alone is useful
(stop accumulating dead links). Feature 2 alone is useful (drive new
links). Feature 3 alone is useful (find unlinked mentions). The
cross-feature wiring in Feature 3 only activates once Feature 1 +
Feature 2 are in.

---

## Open questions

1. **Domain authority data source.** No free DA API. Options: (a)
   manual entry; (b) Ahrefs/Moz free tier; (c) a poor-man's proxy
   (Alexa-style traffic rank from Tranco list). Defaulting to manual
   for MVP — surface a "DA: __" input on backlink rows so the user
   can paste from whichever tool they use.
2. **Google Search Console.** Best source for backlinks Google
   already knows. Requires OAuth setup that's heavier than the rest
   of the dashboard. Defer to post-MVP; today we rely on manual entry
   + Mention Hunter discovery.
3. **HARO API.** HARO doesn't have a public API; replies come via
   email. For MVP, `category='haro'` targets are manually added when
   the user spots a relevant HARO query. Future: auto-scan a HARO-
   forwarded mailbox.

None of these block the MVP — they're future-improvement vectors.
