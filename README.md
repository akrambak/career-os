# Career OS — Bakhouche Akram (AkBak)

Senior fullstack engineer (8y production) layering AI agents on top of an
e-commerce/SMB foundation. This repo is both the playbook and the product:
the system that runs my job search, presence, and GitHub also doubles as the
flagship portfolio piece and seed SaaS.

Build in public. Real name. One project, three outcomes.

---

## Objectives — by 2026-08-08 (3 months)

| #  | Objective                                  | Success metric                                                                       |
|----|--------------------------------------------|--------------------------------------------------------------------------------------|
| O1 | Land FT remote AI/fullstack offer          | ≥3 final-stage interviews in pipeline; ≥10 qualified applications/week sustained     |
| O2 | Establish builder-voice presence           | 1,000 combined LinkedIn + X followers; 1 build-in-public post/day; 4 long-form posts |
| O3 | Ship Career-OS v1 public alpha             | Open-source repo + live demo; 50 GitHub stars; landing page with waitlist            |

Priority if reality pushes back: protect O1 first, O3 second, O2 absorbs slack.

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
- [ ] GitHub profile README + clean pinned repos
- [ ] X/@AkBak bio + first build-in-public thread
- [ ] Posting cadence: LinkedIn 3×/week, X daily, blog weekly

### Phase 1 — Opportunity crawler MVP (Weeks 2–4, ~20h)
Highest leverage: directly serves O1, doubles as the most interesting public
agent demo for O2/O3.

- [ ] Scrapers: RemoteOK, Wellfound, We Work Remotely, HN Who's Hiring, AI boards
- [ ] Postgres schema (jobs, scores, applications, posts)
- [ ] Claude scorer: each job vs profile → 0–100 fit + reasoning
- [ ] Daily digest email (top 5)
- [ ] Open-source from commit 1; tweet each milestone

### Phase 2 — Application agent + tracker (Weeks 5–7, ~25h)
- [ ] Tailored CV / cover-letter generator from job posting + profile
- [ ] Application pipeline tracker (stages, dates, follow-up nudges)
- [ ] First web UI (Next.js, kept minimal)

### Phase 3 — Presence module (Weeks 8–10, ~25h)
The SaaS-shaped piece — by now there is audience and product to point at.

- [ ] Multi-platform post drafter (LinkedIn, X, dev.to, HN)
- [ ] Schedule + queue + manual approval gate
- [ ] Engagement tracking + post-performance analytics

### Phase 4 — GitHub optimizer + public launch (Weeks 11–12, ~15h)
- [ ] Profile analyzer + repo recommendations vs target roles
- [ ] Show HN + Product Hunt + LinkedIn launch
- [ ] Waitlist landing page on bak-dev.com/career-os

---

## Stack

- **Backend / agents:** Python (Claude SDK), self-hosted OSS models via Ollama/vLLM where useful
- **Web:** Next.js (already used on bak-dev.com), Postgres
- **Scrapers:** Playwright + lightweight HTTP fetchers
- **Deploy:** Cloudflare Pages + a small VPS for the always-on crawler

---

## Repo layout

```
.
├── README.md                # this file — the playbook
├── presence/                # copy + assets for site, LinkedIn, X, GitHub profile
│   ├── positioning.md       # headline, taglines, bio variants
│   └── linkedin.md          # LinkedIn rewrite (headline, about, featured post)
└── (phase 1+ code lands here as it ships)
```
