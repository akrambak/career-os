# Career OS — Bakhouche Akram (AkBak)

[![CI](https://github.com/akrambak/career-os/actions/workflows/ci.yml/badge.svg)](https://github.com/akrambak/career-os/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](pyproject.toml)

Senior fullstack engineer (8y production) layering AI agents on top of an
e-commerce/SMB foundation. This repo is both the playbook and the product:
the system that runs my job search (FT remote + freelance), presence, and
GitHub also doubles as the flagship portfolio piece and seed SaaS.

Build in public. Real name. One project, three outcomes.

```
fetch  →  store  →  score  →  draft  →  digest
```

Crawls remote-job and HN-freelance sources, scores each posting against a
profile with Claude, drafts ready-to-send outreach, and emits a Markdown
digest of the top matches.

---

## Objectives — by 2026-08-08 (3 months)

| #  | Objective                                  | Success metric                                                                       |
|----|--------------------------------------------|--------------------------------------------------------------------------------------|
| O1 | Land work — FT remote OR freelance retainer | ≥3 qualified leads/wk (FT final-stage OR freelance scope call); ≥10 applications/wk |
| O2 | Establish builder-voice presence           | 1,000 combined LinkedIn + X followers; 1 build-in-public post/day; 4 long-form posts |
| O3 | Ship Career-OS v1 public alpha             | Open-source repo + live demo; 50 GitHub stars; landing page with waitlist            |

Priority if reality pushes back: protect O1 first, O3 second, O2 absorbs slack.
Within O1, accept whichever channel converts first — freelance retainer or FT offer. Treat them as substitutes, not a hierarchy.

---

## Positioning

> Senior Fullstack Engineer building AI-powered tools for e-commerce & SMBs.
> 8 years shipping PHP/Laravel/Flutter in production. Now layering Claude SDK
> + open-source LLMs on top. Building Career-OS in public.

Why this works: 8 YOE = senior signal; e-commerce = real domain (not toy AI
demos); pivot narrative = current and builder-mode; OSS-models mention =
credibility with technical recruiters.

---

## Phases

### Phase 0 — Visibility scaffolding (Week 1, ~10h)
Get visible before building anything else. Crawler into a void = wasted output.

- [ ] Rewrite bak-dev.com headline + about (lead with new positioning)
- [ ] Cut empty /Modules + /Themes placeholder pages from site
- [ ] Replace placeholder images with real photo + diagrams
- [ ] LinkedIn: headline, about, featured post announcing the build
- [ ] Extract LinkedIn session cookies (li_at, JSESSIONID, bcookie) from a clean logged-in browser session — populate `.env`
- [ ] GitHub profile README + clean pinned repos
- [ ] X/@AkBak bio + first build-in-public thread (manual posting from here on)
- [ ] Claim dev.to/akbak — bio, links, profile photo
- [ ] Claim medium.com/@akbak — bio, links, profile photo (manual posting)
- [ ] Generate dedicated SSH key for VPS deploys: `ssh-keygen -t ed25519 -f ~/.ssh/career_os -C career-os@bak-dev.com` and `ssh-copy-id` to the Debian VPS
- [ ] Posting cadence: LinkedIn 3×/week, X daily, dev.to weekly, Medium monthly, blog as canonical for all
- [ ] Write first long-form post (canonical on bak-dev.com/blog, mirrored to dev.to + Medium with canonical_url)

### Phase 1 — Opportunity crawler MVP (Weeks 2–4, ~20h)
Highest leverage: directly serves O1, doubles as the most interesting public
agent demo for O2/O3.

- [x] Scrapers: RemoteOK, We Work Remotely, HN "Seeking freelancer?"
- [ ] Add scrapers: Wellfound, HN Who's Hiring, EU freelance boards
- [x] Schema (jobs, scores, applications) — SQLite for dev, Postgres-shaped
- [ ] Postgres swap-in (driver behind same `Store` interface)
- [x] Claude scorer: each job vs profile → 0–100 fit + reasoning
- [x] CLI digest (`career-os top` / `career-os digest`)
- [ ] Daily digest email (top 5)
- [ ] Open-source: push to github.com/akrambak/career-os, tweet each milestone

### Phase 2 — Application agent + tracker (Weeks 5–7, ~25h)
- [x] Outreach drafter — scored job → tailored cover-letter / freelance pitch (`career-os draft`)
- [ ] Application pipeline tracker (stages, dates, follow-up nudges)
- [ ] Email-send integration (transactional SMTP)
- [ ] First web UI (Next.js, kept minimal)

### Phase 3 — Presence module (Weeks 8–10, ~25h)
The SaaS-shaped piece — by now there is audience and product to point at.

- [ ] Cross-poster: bak-dev.com/blog → dev.to (API) and Medium (API if legacy token, else clipboard-formatted) with canonical_url back to the blog
- [ ] Multi-platform post drafter (LinkedIn, X, dev.to, Medium, HN)
- [ ] Schedule + queue + manual approval gate
- [ ] Engagement tracking + post-performance analytics across all surfaces

See `presence/cross-posting.md` for the channel-roles + canonical-URL strategy this module operationalizes.

### Phase 4 — GitHub optimizer + public launch (Weeks 11–12, ~15h)
- [ ] Profile analyzer + repo recommendations vs target roles
- [ ] Show HN + Product Hunt + LinkedIn launch
- [ ] Waitlist landing page on bak-dev.com/career-os

---

## Stack

- **Backend / agents:** Python (Claude SDK), self-hosted OSS models via Ollama/vLLM where useful
- **Web:** Next.js (already used on bak-dev.com), Postgres
- **Scrapers:** Playwright + lightweight HTTP fetchers
- **Deploy:** Single Debian VPS hosts bak-dev.com (Next.js), the always-on crawler, and the Career-OS dashboard backend. SSH-key-based deploys. **Exception:** the LinkedIn cookie-based poster runs locally on the user's machine (residential IP, same ASN as the cookie's origin login) to minimize flag risk; talks to the rest of Career-OS via API.

---

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env                          # fill ANTHROPIC_API_KEY at minimum

career-os sources                             # list registered scrapers
career-os fetch                               # crawl all sources → SQLite
career-os score --limit 50                    # score unscored jobs with Claude
career-os score --limit 50 --dry-run          # offline keyword stub (no API key)
career-os top --min-fit 70                    # CLI table of top matches
career-os digest --out today.md --min-fit 65  # markdown digest to file
career-os draft --top 5 --min-fit 70          # generate outreach for top matches
career-os draft <job-key> --dry-run           # offline template, no API key
```

The default SQLite DB lives at `data/career_os.db` (gitignored).
Postgres swap-in is planned for Phase 2.

## Repo layout

```
.
├── README.md                # this file — the playbook
├── pyproject.toml           # package config; installs the `career-os` CLI
├── src/career_os/
│   ├── cli/main.py          # `career-os` CLI: fetch | score | top | digest | sources
│   ├── crawler/run.py       # orchestrates scrapers concurrently
│   ├── scrapers/            # one file per source — drop-in extensible
│   │   ├── remoteok.py      #   live (JSON API)
│   │   ├── weworkremotely.py#   live (RSS, 2 categories)
│   │   └── hn_freelancer.py #   live (HN monthly "Seeking freelancer?" Algolia,
│   │                        #   with stack / budget / location / contact extraction)
│   ├── scorer/claude_scorer.py  # Claude SDK fit-scorer, prompt-cached system block
│   ├── drafter/outreach.py  # Claude SDK outreach generator (FT cover / freelance pitch)
│   ├── digest/render.py     # markdown digest renderer (for email + CLI)
│   ├── db/store.py          # SQLite store with Postgres-shaped schema
│   ├── models.py            # Pydantic models: JobPost, Score, Profile, Channel
│   └── profile.py           # the user's profile fed to the scorer
├── tests/                   # pytest suite
├── scripts/smoke.py         # import-time smoke test
└── presence/                # copy + strategy for site, LinkedIn, X, GitHub profile
    ├── positioning.md       # headline, taglines, bio variants, public handles
    ├── linkedin.md          # LinkedIn rewrite (headline, about, featured post)
    ├── cross-posting.md     # bak-dev.com → dev.to / Medium / LinkedIn / X strategy
    ├── github-profile.md    # akrambak/akrambak README + repo bootstrap checklist
    └── hire-me-page.md      # spec for bak-dev.com/hire-me freelance intake page
```
