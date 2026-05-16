# X thread — Career-OS launch (001)

Numbered for paste-by-paste. Max 280 chars per tweet.
Test each one against `https://twitter.com/your-handle/status/1?text=...` to confirm fit.

---

**1/10**
```
After 8 years shipping production Laravel, PrestaShop, Vue, Flutter for real
e-commerce customers, I'm pivoting into AI engineering.

I'm not throwing away the 8 years. I'm betting the opposite is valuable.

So I'm building Career-OS in public.

github.com/akrambak/career-os
```

**2/10**
```
The bet:

There's no shortage of engineers who can wire up an LLM call.

There's a shortage of engineers who've shipped real products to real customers
AND can build reliable agentic systems.

I want to sit at that intersection.
```

**3/10**
```
Career-OS is an AI agent that runs my own job search and freelance pipeline:

- crawls opportunities
- scores them against my profile with Claude
- drafts tailored outreach
- surfaces a daily digest of the top matches

The system that finds my next gig is the same one I'd ship to a client.
```

**4/10**
```
This weekend's commits:

→ 3 live scrapers: RemoteOK, WeWorkRemotely, HN "Seeking freelancer?"
→ SQLite store (Postgres-shaped schema)
→ Claude SDK fit-scorer w/ prompt caching
→ Outreach drafter (FT cover + freelance pitch variants)
→ CLI: fetch | score | draft | digest

Open-source. MIT. CI on push.
```

**5/10**
```
The interesting source is HN.

Every month HN runs a "Freelancer? Seeking freelancer?" thread. Top-level
comments starting with SEEKING FREELANCER are *real* founder briefs.

I extract stack / budget / location / contact from each, score with Claude,
surface the matches. SNR is 10x LinkedIn.
```

**6/10**
```
Scorer prompt design that mattered:

I'm not asking "is this a good job?"

I'm asking "is this a good job for THIS specific engineer?" — and passing
my own profile as structured JSON: proven stack, new stack, deal breakers,
nice-to-haves.

Calibration in the system prompt: most jobs are 30-55.
```

**7/10**
```
Drafter design that mattered:

Two system prompts — FT cover-letter shape, freelance pitch shape.

Hard rules baked in:
- never invent metrics
- never agree to <2 weeks freelance
- never accept hourly under €60/hr

The model can't soften the floor the way I might in person.
```

**8/10**
```
Why open-source from commit 1:

The project IS the portfolio.

A recruiter or client asking "do you actually ship AI agents in production?"
doesn't have to take my word — the repo is right there, with commits, tests,
CI, and a CLI that runs.

Closed-source "trust me" doesn't convert.
```

**9/10**
```
What's next on the roadmap:

- Wellfound + EU freelance boards
- Postgres swap-in
- Application-pipeline tracker
- Email-send integration
- Public alpha + waitlist this summer

Following along is one ⭐ away: github.com/akrambak/career-os
```

**10/10**
```
I'm open to:

▸ FT remote: senior fullstack where AI is in the brief
▸ Freelance: production AI bolted onto Laravel / PrestaShop / Flutter,
  2-week min, retainer or fixed-scope

DMs open. Email me@bak-dev.com.

Repo: github.com/akrambak/career-os
Site: bak-dev.com/hire-me
```

---

## Posting notes

- Tweet 1 has the link at the bottom (algo prefers content-first hooks).
- Tweet 5–7 are the "technical meat" — these tend to get the most retweets from the dev audience.
- Tweet 10 closes with the explicit ask. Don't omit it.
- Reply with a screenshot of `career-os fetch` output as the 11th post if you want a visual hook above the fold for the quote-tweet view.
- Schedule each tweet 60–90s apart to keep the thread coherent without spamming.
