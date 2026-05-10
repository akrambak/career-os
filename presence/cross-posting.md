# Cross-posting strategy — bak-dev.com / dev.to / Medium / LinkedIn / X

The leverage move: write each piece **once**, on bak-dev.com, then mirror to
the other surfaces with a `canonical_url` pointing back. Audience reads where
they live; SEO juice flows to your domain; no duplicate-content penalty.

---

## Channel roles (do not blur these)

| Channel              | Audience              | Content type                                    | Distribution (locked 2026-05-09)         |
|----------------------|-----------------------|-------------------------------------------------|------------------------------------------|
| **bak-dev.com/blog** | Recruiters, deep readers | Canonical home — every post lives here first  | Self-hosted on Debian VPS                |
| **dev.to**           | Builders, AI/dev tooling crowd | Technical writeups, code, agent walkthroughs | API (free, full)                       |
| **LinkedIn**         | Recruiters, professional network | Short hook adapted from blog post     | Official OAuth (w_member_social) — automated once approved |
| **Medium**           | Broader / business / career-pivot readers | Narrative, "lessons learned", career posts | **Manual paste** (clipboard-formatted) |
| **X / @AkBak**       | Builder network       | Thread version of the blog post                 | **Manual paste** (no API spend)          |

---

## Posting cadence

- **dev.to** — 1 technical post / week (build log of Career-OS milestone)
- **Medium** — 1 narrative post / month (career pivot, lessons, opinion)
- **bak-dev.com/blog** — receives every dev.to + Medium post first as canonical, plus a quarterly long-form retrospective
- **LinkedIn** — 3 posts / week; at least one is a hook + link adaptation of that week's blog post
- **X** — daily. Each blog post becomes one full thread; the rest are off-the-cuff build-in-public moments.

The crawler week, the agent week, the prompt-eval week — each becomes one
dev.to post + the matching LinkedIn hook + the matching X thread + a
paragraph in the next Medium retrospective.

---

## Content split — what goes where

### dev.to (technical, code-heavy)
- "Building an AI job-board crawler with Claude SDK — week N"
- "I asked Claude to score 200 jobs against my profile. Here's what worked."
- "Cheap-mode agents: when Ollama beats a Claude call"
- "MCP for personal use: my desktop now has a job-search tool"
- "How I evaluate my own LinkedIn drafts before posting"

### Medium (narrative, opinion)
- "8 years of fullstack, then I added AI"
- "I'm not an AI engineer pretending to know e-commerce. I'm an e-commerce engineer who learned to build agents."
- "Why I'm building my career change in public"
- "The hidden cost of pivoting after 8 years (and why I'd do it again)"

### bak-dev.com/blog
- All of the above, posted first as canonical
- Plus quarterly retrospectives ("Career-OS, 90 days in")
- Plus any post too on-brand for either platform

### LinkedIn (3/week)
- Mon: hook + insight from this week's dev.to post → link
- Wed: short opinion / observation, no link
- Fri: build-in-public update — what shipped, what's next, what surprised you

### X / @AkBak (daily, themed)
- Mon thread: the same dev.to post, decomposed
- Tue–Thu: shipping moments, screenshots, micro-observations
- Fri: weekly recap thread (3–5 posts: shipped / surprised / next)

---

## The canonical URL pattern (the technical mechanic)

When mirroring a post from `bak-dev.com/blog/foo` to dev.to:

```http
POST /api/articles
api-key: <DEVTO_API_KEY>
content-type: application/json

{
  "article": {
    "title": "...",
    "body_markdown": "...",
    "published": true,
    "canonical_url": "https://bak-dev.com/blog/foo",
    "tags": ["ai", "career", "buildinpublic", "claude"],
    "main_image": "https://bak-dev.com/.../cover.png"
  }
}
```

`canonical_url` tells Google "the original lives at bak-dev.com" — dev.to
won't outrank you in your own search results, and the link equity stacks on
your domain.

Same pattern on Medium (when token is held — see "Medium reality" below).

---

## Channel decisions (2026-05-09)

**Medium → manual paste.** Medium stopped issuing new integration tokens on
2026-01-01, and we've decided to skip the automation path either way.
Career-OS pre-formats the markdown with a canonical_url note in the footer;
you paste it into Medium and set the canonical_url manually under Story
Settings → Advanced.

**X → manual paste.** No API spend. Posting tier on X API v2 is $200/mo;
not worth it at this stage. Career-OS generates thread-formatted drafts to
clipboard / file; you paste them into x.com.

**LinkedIn → official OAuth.** We pursue the formal Marketing Developer
Platform / w_member_social path. Approval can take days-to-weeks; until it
lands, LinkedIn posts go via the same draft-to-clipboard flow. The day
approval is granted, we flip the switch — the drafter doesn't change.

Don't over-invest in Medium — engagement on the platform has declined
materially vs its 2018–2020 peak. It's a complementary surface, not a
primary one. If it stops returning, drop it without ceremony.

---

## API keys / auth

Lives in the project's `.env` (gitignored). See `.env.example` for the
DEVTO_API_KEY and MEDIUM_INTEGRATION_TOKEN fields and how to obtain each.

---

## When this strategy plugs into the build

- **Phase 0 (now):** claim handles, set bios, link to bak-dev.com.
  *No automated posting yet.* Write the first piece manually end-to-end so
  we know the workflow before encoding it.
- **Phase 1 (crawler):** publish weekly dev.to build logs **manually**.
  Get the rhythm. Capture the friction.
- **Phase 3 (presence module):** turn the manual workflow into the
  cross-poster service inside Career-OS — dev.to via API, LinkedIn via
  official OAuth (with clipboard fallback while approval is pending),
  Medium and X always clipboard.
