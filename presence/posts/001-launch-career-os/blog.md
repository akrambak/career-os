---
title: "I built an AI agent that finds freelance gigs for me (in a weekend, in public)"
canonical_url: https://bak-dev.com/blog/career-os-launch
tags: [ai, career, buildinpublic, claude]
cover_image: https://bak-dev.com/blog/career-os-launch/cover.png
status: draft
target_platforms: [bak-dev.com, dev.to, LinkedIn-hook, X-thread]
written_at: 2026-05-16
---

After eight years shipping production Laravel, PrestaShop, Vue, and Flutter
for real e-commerce customers, I'm pivoting hard into AI engineering. And
instead of writing yet another "I'm learning AI" post, I'm shipping the
toolchain itself — open-source, in public, starting today.

**[github.com/akrambak/career-os](https://github.com/akrambak/career-os)**

## The pitch

There's no shortage of engineers who can wire up an LLM call.
There's a shortage of engineers who've actually shipped real products to real
customers AND can build reliable agentic systems.

I want to sit at that intersection. So I'm building Career-OS — an AI agent
that runs my own job search, scores opportunities against my profile, drafts
applications, and manages my online presence. The system that finds my next
gig is the same system I'd ship to a client.

## What I built this weekend

Three live scrapers, a SQLite store, a Claude-powered fit scorer, and a CLI
that produces a markdown digest of the top matches.

```bash
$ career-os fetch
        Crawl results
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ source         ┃ new jobs ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ remoteok       │       99 │
│ weworkremotely │      124 │
│ hn_freelancer  │        1 │
└────────────────┴──────────┘
```

That last source is the interesting one. Every month, Hacker News runs a
"Freelancer? Seeking freelancer?" thread — and the top-level comments
starting with `SEEKING FREELANCER` are real briefs from real founders,
not jobs posted to a board where 800 other engineers already applied.

I parse that thread, drop everything except actual leads, score each one
against my profile with Claude, and surface the top matches. The signal-
to-noise ratio is *radically* better than scraping LinkedIn.

## The scorer

The interesting prompt design: I'm not asking Claude "is this a good job?"
I'm asking "is this a good job *for this specific engineer*?" — and passing
my own profile as structured JSON.

```python
{
  "profile": {
    "headline": "Senior Fullstack (8y) layering AI on top...",
    "proven_stack": ["PHP", "Laravel", "PrestaShop", ...],
    "new_stack": ["Python", "Anthropic Claude SDK", "MCP", ...],
    "target_channels": ["ft", "freelance"],
    "deal_breakers": ["On-site required", "< $60/hr freelance", ...],
    "nice_to_haves": ["AI / LLM in the brief", "e-commerce domain", ...]
  },
  "job": {...}
}
```

The system prompt is explicit about distribution: most jobs are 30–55. A 70+
should mean "worth applying today." 85+ is reserved for unusually aligned
matches. Without that calibration, LLMs default to optimistic and you end up
with 200 "great matches" per day, which is the same as zero.

I cache the system block (it's ~600 tokens and identical every call) — pays
back instantly across a batch.

## Why open-source from commit 1

Two reasons.

**One:** the project is the portfolio. A recruiter asking "do you actually
ship AI agents in production?" doesn't need to take my word — the repo is
right there, with commits, tests, and a CLI that actually runs.

**Two:** the people who want to hire me for freelance AI work are exactly the
people who'd look at a public repo before sending a DM. Closed-source
"trust me" doesn't convert. Open-source "look at the code" does.

## What's next

- More sources: Wellfound, EU freelance boards, niche AI/ML job boards
- Postgres swap-in (the schema's already shaped for it)
- Application-pipeline tracker (stages, follow-ups, dates)
- Tailored cover-letter drafter from job + profile
- Public alpha + waitlist landing on bak-dev.com by end of summer

If you've built something similar — or you want to talk about freelance work
on Laravel/PrestaShop + AI — I'm at me@bak-dev.com.

## I'm open to work

**Freelance:** scoped engagements adding production-grade AI to existing
Laravel / PrestaShop / Vue / Flutter stacks. 2-week minimum, retainer or
fixed-scope. [Book a scope call →](https://bak-dev.com/hire-me)

**Full-time:** fully remote, senior fullstack with AI in the brief, or
AI/agent-systems roles that value a strong shipping background.

Either way: the repo at [github.com/akrambak/career-os](https://github.com/akrambak/career-os)
is the conversation starter.
