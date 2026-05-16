# bak-dev.com/hire-me — inbound conversion page

The single URL every LinkedIn / X / dev.to / GitHub link points at when the
ask is "work with me." Doubles as a qualifying filter so bad-fit leads
self-eliminate before stealing calendar time.

Lives on the existing Next.js bak-dev.com (source location: ask user before
scripting edits — see [[reference_bak_dev_site]]).

---

## Slug + nav

- Canonical URL: `https://bak-dev.com/hire-me`
- Alias: `/freelance`, `/work-with-me` → 301 to `/hire-me`
- Header nav: "Hire me" — always visible, right-aligned, contrast-styled button

---

## Page structure (top → bottom)

### 1. Hero (above the fold)

**H1:** "Hire me to add AI to your existing stack — without burning down what works."

**Subhead:** "Senior fullstack engineer (8y in production). I take Laravel / PrestaShop / Vue / Flutter apps that already serve real customers and bolt on Claude-SDK agents, LLM features, and AI tooling. Without rewriting the world."

**Primary CTA:** `Book a scope call →` (Calendly 25-min slot)
**Secondary CTA:** `me@bak-dev.com` (mailto)

### 2. What I take on (3 cards)

Each card: title, one-paragraph scope, typical timeline, typical price band.

**Card A — AI feature retrofit (2–4 weeks)**
> You have a Laravel or PrestaShop app shipping revenue. You want an AI-powered
> feature in it — semantic search, smart product recommendations, an LLM
> support copilot, agentic checkout flows. I scope, build, and ship it inside
> your existing codebase. Postgres + Claude SDK + your stack — no rewrites,
> no new infra you have to maintain.
> Typical: 2–4 weeks · fixed-scope.

**Card B — Agent system from scratch (4–8 weeks)**
> You need an internal agent — sales-lead enrichment, customer-data pipeline,
> ops-automation bot, anything that scrapes / scores / drafts. I build the
> agent, the evaluation harness so it doesn't silently regress, and the
> ops dashboard so your team can supervise it.
> Typical: 4–8 weeks · fixed-scope or 4-week retainer.

**Card C — Fractional AI-engineer retainer (ongoing)**
> You have a team but no AI engineer. I take 1–2 days/week, pair with your
> developers, review PRs, set prompt-eval guardrails, and ship the LLM
> features your roadmap promised. Minimum 8 weeks.
> Typical: monthly retainer.

### 3. What I won't take on (qualifying filter)

Lead with the no's. This filter is the whole point of the page — every
bad-fit lead that bounces here saves 30 min of intro call.

- ❌ Hourly gigs under €60/hr equivalent
- ❌ "Just talk to me about AI" with no scoped problem
- ❌ Crypto / web3 speculative projects
- ❌ Greenfield rewrites of legacy systems (I'm an AI-feature engineer, not a Java→Rust migration consultant)
- ❌ On-site work — fully remote only
- ❌ Sub-2-week engagements (not enough time to ship anything I'd put my name on)

### 4. Proof strip (logos / metric)

Whatever you have:
- N years in production
- Career-OS itself (live link to GitHub, star count, last commit date — pulled dynamically)
- 1–2 anonymized client stories ("Shipped X for an e-commerce store doing Y/month")
- Stack badges (Laravel · PrestaShop · Vue · Flutter · Claude SDK)

### 5. How it works (4 steps)

1. **Scope call (free, 25 min).** You explain the problem. I tell you whether
   I can solve it, what shape the engagement would be, and a price range. No
   pressure to commit.
2. **Written proposal (within 48h).** Scope, deliverables, timeline, price,
   what's explicitly out of scope. One round of revisions included.
3. **Build sprint.** I work async, ship working code on a feature branch you
   can pull at any time, send Loom updates 2×/week. No daily standups.
4. **Handover.** Code + docs + a recorded walkthrough. 2 weeks of email
   support included.

### 6. FAQ (handle objections before they're sent)

- *Do you sign NDAs?* Yes, standard mutual NDA, sent over before the scope call.
- *Where are you based / what hours?* Remote, European TZ-friendly, FR + EN bilingual.
- *Do you sub-contract?* No. Solo by design.
- *What about IP?* Work-for-hire — all code I write inside your codebase is yours.
- *Can you join our Slack?* Yes, for the duration of the engagement.
- *What's your AI stack opinion?* Claude SDK for production agents; Ollama / vLLM for cheap-mode or self-hosted; Postgres for everything stateful.

### 7. Closing CTA

Repeat the Calendly link + email. Add a line: *"If none of this fits but you
think we should still talk, just email me."* — leaves the door open for the
weird-shaped opportunity that doesn't fit the cards.

---

## Tracking / analytics (bare minimum)

- UTM on every outbound link to `/hire-me` (LinkedIn, X, dev.to, GitHub profile)
- Calendly built-in analytics for booking rate
- Plausible / GA event on the email mailto click
- Weekly review: which channel converts best, what's getting bounce-only traffic

---

## Sequencing — when to build this

This page is the **highest-leverage Phase 0 artifact** for the freelance pillar
of the goal. Until it exists, every freelance signal we generate on LinkedIn / X
falls into a generic "DM me" intake that converts badly.

**Build before:** the LinkedIn rewrite goes live with freelance language.
**Build after:** the first 2–3 Career-OS commits are public on GitHub (so the
proof strip can show real artifacts).

Realistic time budget: 3–4 hours of focused work — copy is mostly in this
file already; the Next.js implementation is a single page + Calendly embed +
the existing site's components.
