"""The 12-week career-sprint plan, structured as seed data for the To-Do page.

Editing this file changes the canonical plan. On next dashboard load, the
seeder reconciles: new items are inserted, existing items keep their checked
state and notes. Items removed from this file stay in the DB (you can delete
them via the UI) — we never silently drop user state.

Sections are rendered as expanders in display order. `sort_order` is the
intra-section order. Priorities: P0 = this week, P1 = this phase, P2 = nice.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedItem:
    section: str
    item: str
    priority: str = "P2"
    due_date: str | None = None  # ISO YYYY-MM-DD
    notes: str | None = None


# ============================================================================
# Phase headers — the sections render in this order.
# ============================================================================

SECTIONS: list[tuple[str, str]] = [
    ("Week 1 — Launch (May 17–24)",
     "Ship what's already drafted. Zero new product work."),
    ("Weeks 2-3 — Outbound Onslaught (May 25 – June 7)",
     "30 personalized pitches/week. The crawler earns its keep."),
    ("Weeks 4-5 — Funnel Tuning (June 8 – 21)",
     "Iterate templates, not the product."),
    ("Week 6 — Pivot Decision (June 22 – 28)",
     "Honest scoring. Narrow the niche if conversion is broken."),
    ("Weeks 7-9 — Wedge Product (June 29 – July 19)",
     "€5k signed by end of week 9."),
    ("Weeks 10-12 — Scale & Close (July 20 – Aug 8)",
     "Cut what doesn't work. Double what does."),
    ("Daily Habits", "The structure that protects deep work."),
    ("Content Rules", "More important than cadence."),
    ("Decision Rules", "Review every Sunday 8pm. 30 min of dashboard time."),
    ("Monetization Wedge — PrestaShop AI Suite",
     "Recommended Phase 3 product. Pick or replace."),
    ("Dashboard Improvements (parking lot)",
     "Build only when funnel is empty for a day."),
]


# ============================================================================
# Items
# ============================================================================

DEFAULT_PLAN: list[SeedItem] = [
    # ---- Week 1 ------------------------------------------------------------
    SeedItem("Week 1 — Launch (May 17–24)",
             "Refresh ANTHROPIC_API_KEY in .env (current value 401s)",
             priority="P0", due_date="2026-05-18"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Run `career-os score --limit 100` on real Claude; read top-10 by hand",
             priority="P0", due_date="2026-05-18"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Hand-edit scorer system prompt if calibration disagrees with gut",
             priority="P0", due_date="2026-05-18"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Replace LinkedIn profile from presence/linkedin.md (90 min)",
             priority="P0", due_date="2026-05-19"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Publish bak-dev.com/blog/career-os-launch (canonical)",
             priority="P0", due_date="2026-05-20"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Deploy bak-dev.com/hire-me from presence/site-snippets/hire-me/page.tsx",
             priority="P0", due_date="2026-05-20"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Mirror to dev.to with canonical_url + cover image",
             priority="P0", due_date="2026-05-21"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Post LinkedIn launch (pin as Featured)",
             priority="P0", due_date="2026-05-22"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Post X thread (10 tweets, 90s apart)",
             priority="P0", due_date="2026-05-22"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Submit Show HN at 08:00 ET Friday",
             priority="P0", due_date="2026-05-22"),
    SeedItem("Week 1 — Launch (May 17–24)",
             "Reply to every comment within 4h (Sat-Sun, no new posts)",
             priority="P0", due_date="2026-05-24"),

    # ---- Weeks 2-3 ----------------------------------------------------------
    SeedItem("Weeks 2-3 — Outbound Onslaught (May 25 – June 7)",
             "30 outbound pitches/wk via `career-os draft` (60% freelance, 40% FT)",
             priority="P0", due_date="2026-06-07"),
    SeedItem("Weeks 2-3 — Outbound Onslaught (May 25 – June 7)",
             "Track every pitch in `career-os apply` — funnel must reflect reality",
             priority="P0", due_date="2026-06-07"),
    SeedItem("Weeks 2-3 — Outbound Onslaught (May 25 – June 7)",
             "Daily: 2 LinkedIn micro-posts + 1 X build-log",
             priority="P1", due_date="2026-06-07"),
    SeedItem("Weeks 2-3 — Outbound Onslaught (May 25 – June 7)",
             "Weekly: 1 dev.to technical post (Fridays)",
             priority="P1", due_date="2026-06-07"),
    SeedItem("Weeks 2-3 — Outbound Onslaught (May 25 – June 7)",
             "HARD RULE: no new Career-OS features until 30/wk pitches for 2 wks straight",
             priority="P0", due_date="2026-06-07"),

    # ---- Weeks 4-5 ----------------------------------------------------------
    SeedItem("Weeks 4-5 — Funnel Tuning (June 8 – 21)",
             "Kill any outreach template with <8% reply over 30 sends",
             priority="P0", due_date="2026-06-21"),
    SeedItem("Weeks 4-5 — Funnel Tuning (June 8 – 21)",
             "A/B opener line on top-2 highest-volume templates",
             priority="P1", due_date="2026-06-21"),
    SeedItem("Weeks 4-5 — Funnel Tuning (June 8 – 21)",
             "Tighten content topic if engagement is flat (narrow > broaden)",
             priority="P1", due_date="2026-06-21"),

    # ---- Week 6 (pivot) -----------------------------------------------------
    SeedItem("Week 6 — Pivot Decision (June 22 – 28)",
             "Honest scoring: pipeline ≥ €20k AND ≥3 calls/wk? → stay course",
             priority="P0", due_date="2026-06-28"),
    SeedItem("Week 6 — Pivot Decision (June 22 – 28)",
             "If pipeline < €10k AND <2 calls/wk: narrow to ONE wedge",
             priority="P0", due_date="2026-06-28"),
    SeedItem("Week 6 — Pivot Decision (June 22 – 28)",
             "Wedge candidate A: PrestaShop AI for €5-20M/yr stores (recommended)",
             priority="P1", due_date="2026-06-28"),
    SeedItem("Week 6 — Pivot Decision (June 22 – 28)",
             "Wedge candidate B: Claude-SDK for European Laravel agencies",
             priority="P2", due_date="2026-06-28"),
    SeedItem("Week 6 — Pivot Decision (June 22 – 28)",
             "Wedge candidate C: AI support copilots for Laravel SaaS startups",
             priority="P2", due_date="2026-06-28"),

    # ---- Weeks 7-9 (wedge product) -----------------------------------------
    SeedItem("Weeks 7-9 — Wedge Product (June 29 – July 19)",
             "Commit to ONE monetizable side-product",
             priority="P0", due_date="2026-06-30"),
    SeedItem("Weeks 7-9 — Wedge Product (June 29 – July 19)",
             "MVP shipped in 14 days (sell only after first version exists)",
             priority="P0", due_date="2026-07-13"),
    SeedItem("Weeks 7-9 — Wedge Product (June 29 – July 19)",
             "Sell to 3 buyers from warm DM list",
             priority="P0", due_date="2026-07-19"),
    SeedItem("Weeks 7-9 — Wedge Product (June 29 – July 19)",
             "€5k signed (FT offer counts at ~€8k or monthly equiv)",
             priority="P0", due_date="2026-07-19"),

    # ---- Weeks 10-12 (scale + close) ---------------------------------------
    SeedItem("Weeks 10-12 — Scale & Close (July 20 – Aug 8)",
             "Cut channels that aren't converting; double the one that is",
             priority="P0", due_date="2026-08-08"),
    SeedItem("Weeks 10-12 — Scale & Close (July 20 – Aug 8)",
             "Public 90-day retrospective with real numbers (blog + all surfaces)",
             priority="P1", due_date="2026-08-01"),
    SeedItem("Weeks 10-12 — Scale & Close (July 20 – Aug 8)",
             "By Aug 8: signed FT offer OR €5k+ retainer OR €1k+ MRR",
             priority="P0", due_date="2026-08-08"),

    # ---- Daily Habits ------------------------------------------------------
    SeedItem("Daily Habits",
             "07:00–09:00 Deep work block 1 (paid client OR product build)",
             priority="P0"),
    SeedItem("Daily Habits",
             "09:00–10:00 Outreach: send 6 cold pitches via `career-os draft`",
             priority="P0"),
    SeedItem("Daily Habits",
             "10:00–10:30 Reply to overnight DMs + LinkedIn comments",
             priority="P0"),
    SeedItem("Daily Habits",
             "10:30–12:30 Deep work block 2",
             priority="P0"),
    SeedItem("Daily Habits",
             "13:30–15:30 Calls / interviews / scope sessions",
             priority="P0"),
    SeedItem("Daily Habits",
             "15:30–17:00 Deep work block 3 (system improvement OR product)",
             priority="P0"),
    SeedItem("Daily Habits",
             "17:00–18:00 Content: write tomorrow's posts, schedule them",
             priority="P0"),
    SeedItem("Daily Habits",
             "18:00 HARD STOP. Sunday OFF — phone in another room.",
             priority="P0"),

    # ---- Content Rules -----------------------------------------------------
    SeedItem("Content Rules",
             "Always show the artifact (screenshot of CLI / scored job / real reply)",
             priority="P1"),
    SeedItem("Content Rules",
             "Always quote numbers — '12% reply rate' not 'good replies'",
             priority="P1"),
    SeedItem("Content Rules",
             "Lead with the surprising thing, not 'I built X'",
             priority="P1"),
    SeedItem("Content Rules",
             "NEVER 'I'm passionate' / 'I'd love' — senior engineers don't audition",
             priority="P1"),
    SeedItem("Content Rules",
             "Reply to every DM within 4h during business hours",
             priority="P0"),

    # ---- Decision Rules ----------------------------------------------------
    SeedItem("Decision Rules",
             "Content piece gets 0 replies in 24h → archive template, don't iterate",
             priority="P1"),
    SeedItem("Decision Rules",
             "Cold template <8% reply over 30 sends → kill, rewrite from best reply",
             priority="P1"),
    SeedItem("Decision Rules",
             "Freelance lead no call within 7 days of first contact → drop",
             priority="P1"),
    SeedItem("Decision Rules",
             "Paid call >45 min, no price question → being shopped, end + send proposal",
             priority="P1"),
    SeedItem("Decision Rules",
             "GitHub stars not moving 25%/wk → last post hook was weak",
             priority="P1"),
    SeedItem("Decision Rules",
             "Sunday 8pm: 30-min dashboard review, move 1 red KPI green next week",
             priority="P0"),

    # ---- Monetization Wedge ------------------------------------------------
    SeedItem("Monetization Wedge — PrestaShop AI Suite",
             "Module 1: AI Product Description Generator (€99 one-time)",
             priority="P1"),
    SeedItem("Monetization Wedge — PrestaShop AI Suite",
             "Module 2: Smart Search with embeddings (€249 one-time)",
             priority="P1"),
    SeedItem("Monetization Wedge — PrestaShop AI Suite",
             "Distribute via PrestaShop addons marketplace + direct on bak-dev.com",
             priority="P2"),
    SeedItem("Monetization Wedge — PrestaShop AI Suite",
             "Year-1 target: €15-30k with 3-5h/wk maintenance",
             priority="P2"),

    # ---- Dashboard Improvements (parking lot) ------------------------------
    SeedItem("Dashboard Improvements (parking lot)",
             "KPI tab — Tier 1/2/3 metrics with weekly snapshots",
             priority="P1"),
    SeedItem("Dashboard Improvements (parking lot)",
             "Outreach Templates page — per-template reply-rate tracking",
             priority="P2"),
    SeedItem("Dashboard Improvements (parking lot)",
             "Follow-up Nudges — email if `sent` stage > 7 days without reply",
             priority="P2"),
    SeedItem("Dashboard Improvements (parking lot)",
             "Per-source conversion deep-dive — which sources actually close",
             priority="P2"),
    SeedItem("Dashboard Improvements (parking lot)",
             "Scorer eval trend chart — calibration over time",
             priority="P2"),
]
