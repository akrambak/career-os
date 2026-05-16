# GitHub presence — github.com/akrambak

Two artifacts here:

1. **Profile README** — content for the `akrambak/akrambak` special repo (renders on github.com/akrambak).
2. **Repo bootstrap checklist** — manual steps to create `akrambak/career-os` and link everything.

---

## 1. Profile README — paste into `akrambak/akrambak/README.md`

```markdown
### Hi, I'm Akram — Senior Fullstack Engineer (8y) layering AI on top

I ship production code. Eight years of PHP / Laravel / PrestaShop / Vue / Flutter
for real e-commerce and SMB customers. Now bringing Claude SDK + open-source
LLMs into that same stack — and building the toolchain in public.

**🧪 Current build — [Career-OS](https://github.com/akrambak/career-os)**
An AI-agent system that crawls opportunities, scores them against my profile
with Claude, drafts tailored applications, and manages my online presence
end-to-end. Open-source from commit 1. Public alpha + SaaS landing this summer.

**🛠 The proven stack**
PHP · Laravel · CodeIgniter · PrestaShop (modules + themes, 1.6 → 8.x) ·
Vue · Flutter · Dart · Firebase · Postgres · MySQL

**🤖 The new layer**
Python · Anthropic Claude SDK · MCP · agentic patterns · Ollama · vLLM ·
prompt evaluations

**📬 Open to**
- **FT remote** — senior fullstack roles where AI is in the brief, or
  AI / agent-systems roles that value a real shipping background
- **Freelance / contract** — production-grade AI features bolted onto existing
  Laravel / PrestaShop / Vue / Flutter stacks · 2-week minimum · retainer or fixed-scope

Bilingual FR / EN.

🔗 [bak-dev.com](https://bak-dev.com)  ·  ✉ me@bak-dev.com  ·  𝕏 [@AkBak](https://x.com/AkBak)
```

**Why these blocks, in this order:**
- Headline first — recruiters scan for "senior" + "AI" in the first sentence.
- Career-OS link second — proof, not claims. The repo IS the portfolio.
- Stacks third — the moment they want to skim for keywords, they hit them.
- "Open to" last — they've earned the contact info by reading this far.

---

## 2. Repo bootstrap checklist

User does these manually (need browser-auth'd GitHub session).

- [ ] Create public repo `akrambak/career-os` — description: *"AI-agent system that runs my job search and online presence. Built in public."*
- [ ] License: MIT (already in `pyproject.toml`; add `LICENSE` file at root)
- [ ] Topics: `claude`, `anthropic`, `ai-agents`, `job-search`, `freelance`, `build-in-public`, `python`
- [ ] Add repo URL to bak-dev.com home + LinkedIn featured section
- [ ] Pin `career-os` on profile (after creating the special `akrambak/akrambak` repo)
- [ ] Create the special profile repo: `akrambak/akrambak` (must match username exactly), paste the README above
- [ ] Replace `<your-installation-name>` with `https://github.com/akrambak/career-os` in any internal links once the repo exists
- [ ] Push the local repo at `/home/ultra9-ubuntu/Jobs` to `akrambak/career-os` once happy with the public-facing README

---

## 3. First public commit message (when ready)

```
Initial public scaffold: crawler, scorer, digest

- Three live scrapers: RemoteOK (API), WeWorkRemotely (RSS),
  HN monthly "Seeking freelancer?" (Algolia)
- SQLite store with Postgres-shaped schema (jobs / scores / applications)
- Claude SDK scorer with prompt caching on the system block
- CLI: fetch | score | top | digest | sources
- Postcard architecture — each scraper is a 50-line file; new sources are drop-in

Why public on day one: the project is also the portfolio. The crawler that
finds my next gig is the same crawler I'd ship to a client. Building this
in the open is the most honest credential I can produce.
```

---

## 4. Cadence after the first push

- **Weekly:** one commit-stream tweet ("this week in Career-OS") with the diff
- **Per milestone:** new scraper, new scorer model, new UI surface → blog post + dev.to mirror + LinkedIn hook (see [`cross-posting.md`](cross-posting.md))
- **Stars to chase first:** 50 by Aug 8 (O3 target). Path: HN Show, Product Hunt, dev.to "I built X" posts, AI-tooling subreddits.
