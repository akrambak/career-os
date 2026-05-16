# Post 001 — Career-OS launch

Canonical: bak-dev.com/blog/career-os-launch (draft, not yet published)

## Files

| File | Surface | Status | Notes |
|------|---------|--------|-------|
| `blog.md` | bak-dev.com/blog | draft | The canonical version; publish first. |
| `devto.md` | dev.to | draft | Frontmatter has `canonical_url`; flip `published: true` once blog is live. |
| `linkedin.md` | LinkedIn | ready | Paste verbatim. Posting-time notes inside. |
| `x-thread.md` | X | ready | 10 tweets, paste-by-paste. |

## Publishing order

1. **bak-dev.com/blog** — publish the canonical post. This is the URL all
   the others point at. Without it live, the `canonical_url` field in
   devto.md is pointing at a 404.
2. **dev.to** — paste `devto.md` (the dev.to UI accepts the frontmatter).
   Set `published: true` after a final preview.
3. **LinkedIn** — post the body from `linkedin.md`. Pin as Featured after 48h.
4. **X** — post the thread from `x-thread.md`, 60–90s between tweets.

## Cover image

Needed on bak-dev.com/blog and dev.to. Suggested:
- A terminal screenshot of `career-os fetch` output (the table with 224 jobs).
- Overlay a single-sentence headline: "Career-OS — find freelance gigs with Claude."
- 1600×836 (dev.to-friendly aspect ratio).

## Tracking

Tag every link with UTM params so we can see which surface drives the most repo stars:
- Blog → no UTM (we own the domain)
- dev.to → `?utm_source=devto&utm_medium=post&utm_campaign=launch001`
- LinkedIn → `?utm_source=linkedin&utm_medium=hook&utm_campaign=launch001`
- X → `?utm_source=x&utm_medium=thread&utm_campaign=launch001`

Star-count delta over the first 72h is the only real metric for this launch.
