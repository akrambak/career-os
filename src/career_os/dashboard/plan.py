"""The career-asset plan, structured as seed data for the To-Do page.

Optimized for: limited active hours, async-first delivery, compounding public
artifacts over volume outreach.

Positioning is ADDITIVE — 8 years of proven PHP / Laravel / PrestaShop / Flutter
e-commerce work, NOW LAYERING five new domains on top: AI engineering,
TypeScript, Solidity / blockchain, and trading bots. The "8y in production
+ new AI/web3 layer" narrative is the moat — most AI engineers cannot ship
a PrestaShop module; most PrestaShop devs cannot ship an agent.

The GitHub profile is the showroom.

Editing this file changes the canonical plan. On next dashboard load, the
sync button reconciles: new items inserted, existing items keep their
checked state + notes, seeded items removed from the plan get deleted.
Ad-hoc items (added via the UI) are never touched by sync.

Strategy rationale (don't trim from this file — it's the README of the plan):
  * Outreach volume is expensive in active hours. Replaced with 5 quality
    DMs/wk that pitch a specific shipped artifact.
  * Public open-source assets compound while you rest. Each repo, npm
    package, contract, or backtest log accrues stars + DMs over time.
  * Async clients (web3, AI startups, audit firms) tolerate non-standard
    working styles. Pre-negotiate async-only terms in writing every time.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedItem:
    section: str
    item: str
    priority: str = "P2"
    due_date: str | None = None
    notes: str | None = None


SECTIONS: list[tuple[str, str]] = [
    ("Setup — GitHub Profile as Showroom",
     "One-time foundation. Make github.com/akrambak the first impression."),
    ("Asset 1 — AI Agents (Career-OS)",
     "Already public. Enrich; ship demo; drive contributors."),
    ("Asset 2 — TypeScript Library on npm",
     "One shipped npm package. Passive distribution. Type-safe = trust signal."),
    ("Asset 3 — Blockchain Public Showcase",
     "One open-source contract OR one public audit. Async-friendly + high pay."),
    ("Asset 4 — Trading Bot Framework",
     "Public framework + live backtest log. Compounds while you sleep."),
    ("Asset 5 — E-commerce AI Wedge (PrestaShop / Laravel)",
     "Your defensible niche. 8y of expertise + AI = premium-priced modules."),
    ("Async Outreach — 5/wk, batch",
     "Quality over volume. Pitch a deliverable, never yourself."),
    ("Content — 1/wk, batch friendly",
     "Each post links to a GitHub artifact. No artifact = no post."),
    ("Daily Habits — Accessibility-Adapted",
     "1 deep block + 1 short block. Flexible. Sunday OFF, non-negotiable."),
    ("Decision Rules — Cut What Doesn't Compound",
     "Async-friendly thresholds. Stars are the leading indicator."),
    ("Monetization Wedge — Pick at 90 days",
     "Wait until ONE asset shows traction. Then commit."),
]


DEFAULT_PLAN: list[SeedItem] = [
    # ---- Setup — GitHub Profile ---------------------------------------------
    SeedItem("Setup — GitHub Profile as Showroom",
             "Create akrambak/akrambak repo (special profile README)",
             priority="P0", due_date="2026-05-24"),
    SeedItem("Setup — GitHub Profile as Showroom",
             "Profile README: 8y fullstack (PHP/Laravel/PrestaShop/Flutter) "
             "+ now AI/TS/blockchain/trading + async-only signal",
             priority="P0", due_date="2026-05-24"),
    SeedItem("Setup — GitHub Profile as Showroom",
             "Pin career-os; reserve 5 more pin slots for upcoming assets",
             priority="P0", due_date="2026-05-24"),
    SeedItem("Setup — GitHub Profile as Showroom",
             "Stack badges — proven: PHP · Laravel · PrestaShop · Flutter · Vue",
             priority="P1", due_date="2026-05-31"),
    SeedItem("Setup — GitHub Profile as Showroom",
             "Stack badges — new layer: TypeScript · Solidity · Python · Claude SDK",
             priority="P1", due_date="2026-05-31"),
    SeedItem("Setup — GitHub Profile as Showroom",
             "Enable GitHub Sponsors (passive funding rail)",
             priority="P1", due_date="2026-05-31"),
    SeedItem("Setup — GitHub Profile as Showroom",
             "Add 'Available for async, project-based work' callout",
             priority="P1", due_date="2026-05-31"),
    SeedItem("Setup — GitHub Profile as Showroom",
             "Add GitHub stats card + top-languages widget",
             priority="P2"),
    SeedItem("Setup — GitHub Profile as Showroom",
             "Pick one repo per week to star/fork — visible activity signals life",
             priority="P2"),

    # ---- Asset 1: AI Agents (Career-OS) ------------------------------------
    SeedItem("Asset 1 — AI Agents (Career-OS)",
             "Tag v0.2.0 release with current feature set",
             priority="P0", due_date="2026-05-31"),
    SeedItem("Asset 1 — AI Agents (Career-OS)",
             "Record asciinema cast: fetch → score → draft → digest → dashboard",
             priority="P0", due_date="2026-05-31"),
    SeedItem("Asset 1 — AI Agents (Career-OS)",
             "Add demo GIF/cast to README (single biggest star driver)",
             priority="P0", due_date="2026-05-31"),
    SeedItem("Asset 1 — AI Agents (Career-OS)",
             "Label 3 good-first-issue items to invite contributions",
             priority="P1"),
    SeedItem("Asset 1 — AI Agents (Career-OS)",
             "Submit to awesome-claude, awesome-ai-agents, awesome-cli lists",
             priority="P1"),
    SeedItem("Asset 1 — AI Agents (Career-OS)",
             "Public Roadmap as GitHub Project (signals momentum)",
             priority="P2"),

    # ---- Asset 2: TypeScript Library ---------------------------------------
    SeedItem("Asset 2 — TypeScript Library on npm",
             "Pick ONE itch (recommend: @akrambak/ai-eval — TS LLM eval harness)",
             priority="P0", due_date="2026-06-07"),
    SeedItem("Asset 2 — TypeScript Library on npm",
             "Write the public API in TYPES.md BEFORE the implementation",
             priority="P0", due_date="2026-06-07"),
    SeedItem("Asset 2 — TypeScript Library on npm",
             "Ship v0.1.0 to npm with full types + 2 working examples",
             priority="P0", due_date="2026-06-21"),
    SeedItem("Asset 2 — TypeScript Library on npm",
             "GitHub Actions: build + test on PR, publish on tag",
             priority="P1"),
    SeedItem("Asset 2 — TypeScript Library on npm",
             "README badges: npm version, downloads, CI status, license",
             priority="P1"),
    SeedItem("Asset 2 — TypeScript Library on npm",
             "Launch post on dev.to + LinkedIn when v0.1.0 is live",
             priority="P1"),

    # ---- Asset 3: Blockchain Showcase --------------------------------------
    SeedItem("Asset 3 — Blockchain Public Showcase",
             "Pick path: A) own open-source contract  B) public audit writeup",
             priority="P0", due_date="2026-06-14"),
    SeedItem("Asset 3 — Blockchain Public Showcase",
             "Foundry scaffold: src/test/script + GH Actions for forge test",
             priority="P0", due_date="2026-06-21"),
    SeedItem("Asset 3 — Blockchain Public Showcase",
             "Ship one publishable contract (vesting / multisig / small DeFi primitive)",
             priority="P0", due_date="2026-07-05"),
    SeedItem("Asset 3 — Blockchain Public Showcase",
             "Full test coverage + Slither + invariant tests with Echidna",
             priority="P1"),
    SeedItem("Asset 3 — Blockchain Public Showcase",
             "Deploy to Sepolia, verify on Etherscan, link from README",
             priority="P1"),
    SeedItem("Asset 3 — Blockchain Public Showcase",
             "Audit-style writeup (of your own contract) → portfolio piece",
             priority="P1"),
    SeedItem("Asset 3 — Blockchain Public Showcase",
             "When ready: one Code4rena / Sherlock contest as solo (async-friendly)",
             priority="P2"),

    # ---- Asset 4: Trading Bot Framework ------------------------------------
    SeedItem("Asset 4 — Trading Bot Framework",
             "Pick stack: ccxt + TypeScript (unify portfolio) OR Python+freqtrade",
             priority="P0", due_date="2026-06-14"),
    SeedItem("Asset 4 — Trading Bot Framework",
             "Scaffold repo: data fetch + backtest engine + 1 simple strategy",
             priority="P0", due_date="2026-06-28"),
    SeedItem("Asset 4 — Trading Bot Framework",
             "Ship first reproducible backtest (BTC trend-follow or mean-reversion)",
             priority="P0", due_date="2026-07-12"),
    SeedItem("Asset 4 — Trading Bot Framework",
             "Public backtest dashboard (reuse Career-OS Streamlit pattern)",
             priority="P1"),
    SeedItem("Asset 4 — Trading Bot Framework",
             "Paper-trading log auto-committed daily via GH Actions cron",
             priority="P1"),
    SeedItem("Asset 4 — Trading Bot Framework",
             "Monthly 'strategy of the month' writeup — post results, not promises",
             priority="P2"),

    # ---- Asset 5: E-commerce AI Wedge --------------------------------------
    SeedItem("Asset 5 — E-commerce AI Wedge (PrestaShop / Laravel)",
             "Pick first module — recommend: PrestaShop AI Product Description "
             "Generator (€99 one-time)",
             priority="P0", due_date="2026-06-21"),
    SeedItem("Asset 5 — E-commerce AI Wedge (PrestaShop / Laravel)",
             "Scaffold PrestaShop 8.x module repo + GH Actions CI",
             priority="P0", due_date="2026-06-28"),
    SeedItem("Asset 5 — E-commerce AI Wedge (PrestaShop / Laravel)",
             "Ship v0.1.0 of the description-generator module (Claude SDK backend)",
             priority="P0", due_date="2026-07-12"),
    SeedItem("Asset 5 — E-commerce AI Wedge (PrestaShop / Laravel)",
             "Second module — PrestaShop Smart Search with embeddings (€249)",
             priority="P1"),
    SeedItem("Asset 5 — E-commerce AI Wedge (PrestaShop / Laravel)",
             "Composer package: claude-for-laravel (open-core, Pro tier later)",
             priority="P1"),
    SeedItem("Asset 5 — E-commerce AI Wedge (PrestaShop / Laravel)",
             "List both modules on PrestaShop addons marketplace (~30% rev share)",
             priority="P1"),
    SeedItem("Asset 5 — E-commerce AI Wedge (PrestaShop / Laravel)",
             "Direct sales on bak-dev.com (Gumroad / Lemon Squeezy for fulfillment)",
             priority="P2"),

    # ---- Async Outreach ---------------------------------------------------
    SeedItem("Async Outreach — 5/wk, batch",
             "5 highly-tailored DMs per week, NEVER 30. Quality > volume.",
             priority="P0"),
    SeedItem("Async Outreach — 5/wk, batch",
             "Every pitch references a specific artifact you shipped",
             priority="P0"),
    SeedItem("Async Outreach — 5/wk, batch",
             "Pre-negotiate async-only working style in the FIRST reply",
             priority="P0"),
    SeedItem("Async Outreach — 5/wk, batch",
             "Targets — new domains: web3 founders, AI startup CTOs, trading firms",
             priority="P1"),
    SeedItem("Async Outreach — 5/wk, batch",
             "Targets — proven stack: EU Laravel agencies, PrestaShop store owners "
             "(€5-20M/yr revenue), Flutter shops needing AI features",
             priority="P1"),
    SeedItem("Async Outreach — 5/wk, batch",
             "Engage on GitHub issues + crypto/AI Discords FIRST, cold DM last",
             priority="P1"),
    SeedItem("Async Outreach — 5/wk, batch",
             "Batch the 5 weekly DMs in ONE good-energy session, not daily",
             priority="P1"),

    # ---- Content ---------------------------------------------------------
    SeedItem("Content — 1/wk, batch friendly",
             "1 substantive post per week (any platform). 12 hours/yr earns this slot.",
             priority="P0"),
    SeedItem("Content — 1/wk, batch friendly",
             "Batch 4 posts in one good-energy session, schedule across the month",
             priority="P0"),
    SeedItem("Content — 1/wk, batch friendly",
             "Rotate 5 domains: AI · TypeScript · Blockchain · Trading · "
             "E-commerce (Laravel/PrestaShop)",
             priority="P0"),
    SeedItem("Content — 1/wk, batch friendly",
             "Every post links to a GitHub artifact. No artifact = no post.",
             priority="P1"),
    SeedItem("Content — 1/wk, batch friendly",
             "Cross-post: blog (canonical) → dev.to → LinkedIn hook → X thread",
             priority="P1"),
    SeedItem("Content — 1/wk, batch friendly",
             "Use voice dictation / drafting tools — write less, ship same",
             priority="P1"),

    # ---- Daily Habits (Adapted) ------------------------------------------
    SeedItem("Daily Habits — Accessibility-Adapted",
             "1 deep block / day (90-120 min) — building only, no comms",
             priority="P0"),
    SeedItem("Daily Habits — Accessibility-Adapted",
             "1 short block / day (30-45 min) — content OR outreach OR community",
             priority="P0"),
    SeedItem("Daily Habits — Accessibility-Adapted",
             "Flex timing — work when energy is high, rest when it's not",
             priority="P0"),
    SeedItem("Daily Habits — Accessibility-Adapted",
             "Low-energy day = maintenance mode: reply to issues, RT relevant",
             priority="P1"),
    SeedItem("Daily Habits — Accessibility-Adapted",
             "NO daily standups, NO unprepared calls, NO synchronous demos",
             priority="P0"),
    SeedItem("Daily Habits — Accessibility-Adapted",
             "Sunday OFF — non-negotiable. Energy is the only finite resource.",
             priority="P0"),

    # ---- Decision Rules --------------------------------------------------
    SeedItem("Decision Rules — Cut What Doesn't Compound",
             "Asset gets <5 stars in 90 days → archive, don't iterate",
             priority="P1"),
    SeedItem("Decision Rules — Cut What Doesn't Compound",
             "Outreach template <15% reply over 20 sends → kill, rewrite",
             priority="P1"),
    SeedItem("Decision Rules — Cut What Doesn't Compound",
             "Audit work pays more than retainer? → drop retainer, focus audits",
             priority="P1"),
    SeedItem("Decision Rules — Cut What Doesn't Compound",
             "Active hours done before deep block finished? → STOP. Tomorrow.",
             priority="P0"),
    SeedItem("Decision Rules — Cut What Doesn't Compound",
             "Sunday 30-min review: which artifact got most stars? Do more.",
             priority="P0"),
    SeedItem("Decision Rules — Cut What Doesn't Compound",
             "TS lib has 0 stars at 30 days → pivot the package, don't retry",
             priority="P1"),

    # ---- Monetization Wedge ----------------------------------------------
    SeedItem("Monetization Wedge — Pick at 90 days",
             "Wait until ONE asset has clear traction before committing",
             priority="P1"),
    SeedItem("Monetization Wedge — Pick at 90 days",
             "Candidate A: PrestaShop AI Suite (€99-€249/license, marketplace "
             "distribution, defensible niche — recommended)",
             priority="P1"),
    SeedItem("Monetization Wedge — Pick at 90 days",
             "Candidate B: smart contract audits (async, €2-10k/audit, prestige)",
             priority="P1"),
    SeedItem("Monetization Wedge — Pick at 90 days",
             "Candidate C: trading bot SaaS (subscription, runs without you)",
             priority="P1"),
    SeedItem("Monetization Wedge — Pick at 90 days",
             "Candidate D: AI agent async consulting on Laravel stacks "
             "(written deliverables only, €/day premium for async-only)",
             priority="P1"),
    SeedItem("Monetization Wedge — Pick at 90 days",
             "Whichever you pick: pre-negotiate async-only terms in writing",
             priority="P0"),
]
