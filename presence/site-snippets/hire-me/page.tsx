// Drop into app/hire-me/page.tsx in the bak-dev.com Next.js project.
// Adjust the `CALENDLY_URL` and the import paths if the project uses
// different shadcn/ui or button components. Tailwind utility classes are used
// directly so this works with a standard Next.js 14+ App Router setup.

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Hire me — Bakhouche Akram | AI features on top of your existing stack",
  description:
    "Senior fullstack engineer (8y). I bolt production-grade AI onto Laravel / PrestaShop / Vue / Flutter apps. 2-week minimum, retainer or fixed-scope.",
  alternates: { canonical: "https://bak-dev.com/hire-me" },
  openGraph: {
    title: "Hire me — AI features on top of your existing stack",
    description:
      "Senior fullstack engineer adding production-grade AI to Laravel / PrestaShop / Vue / Flutter apps. 2-week minimum.",
    url: "https://bak-dev.com/hire-me",
    type: "website",
  },
};

const CALENDLY_URL = "https://calendly.com/akbak/scope-call"; // <-- replace with real
const EMAIL = "me@bak-dev.com";

const ENGAGEMENTS = [
  {
    title: "AI feature retrofit",
    timeline: "2–4 weeks · fixed-scope",
    body:
      "You have a Laravel or PrestaShop app shipping revenue. You want an AI-powered feature in it — semantic search, smart product recommendations, an LLM support copilot, agentic checkout flows. I scope, build, and ship it inside your existing codebase. Postgres + Claude SDK + your stack — no rewrites, no new infra you have to maintain.",
  },
  {
    title: "Agent system from scratch",
    timeline: "4–8 weeks · fixed-scope or 4-week retainer",
    body:
      "You need an internal agent — sales-lead enrichment, customer-data pipeline, ops-automation bot, anything that scrapes / scores / drafts. I build the agent, the evaluation harness so it doesn't silently regress, and the ops dashboard so your team can supervise it.",
  },
  {
    title: "Fractional AI-engineer retainer",
    timeline: "Ongoing · 8-week minimum",
    body:
      "You have a team but no AI engineer. I take 1–2 days/week, pair with your developers, review PRs, set prompt-eval guardrails, and ship the LLM features your roadmap promised. Monthly retainer.",
  },
];

const WONT_TAKE = [
  "Hourly gigs under €60/hr equivalent",
  "\"Just talk to me about AI\" with no scoped problem",
  "Crypto / web3 speculative projects",
  "Greenfield rewrites of legacy systems",
  "On-site work — fully remote only",
  "Sub-2-week engagements",
];

const STEPS = [
  {
    n: 1,
    title: "Scope call (free, 25 min)",
    body:
      "You explain the problem. I tell you whether I can solve it, what shape the engagement would be, and a price range. No pressure to commit.",
  },
  {
    n: 2,
    title: "Written proposal (within 48h)",
    body:
      "Scope, deliverables, timeline, price, what's explicitly out of scope. One round of revisions included.",
  },
  {
    n: 3,
    title: "Build sprint",
    body:
      "I work async, ship working code on a feature branch you can pull at any time, send Loom updates 2×/week. No daily standups.",
  },
  {
    n: 4,
    title: "Handover",
    body:
      "Code + docs + a recorded walkthrough. 2 weeks of email support included.",
  },
];

const FAQ = [
  { q: "Do you sign NDAs?", a: "Yes — standard mutual NDA, sent over before the scope call." },
  { q: "Where are you based / what hours?", a: "Remote, European TZ-friendly, FR + EN bilingual." },
  { q: "Do you sub-contract?", a: "No. Solo by design." },
  { q: "What about IP?", a: "Work-for-hire — all code I write inside your codebase is yours." },
  { q: "Can you join our Slack?", a: "Yes, for the duration of the engagement." },
];

export default function HireMePage() {
  return (
    <main className="mx-auto max-w-3xl px-6 py-16">
      {/* Hero */}
      <section className="mb-16">
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Hire me to add AI to your existing stack — without burning down what works.
        </h1>
        <p className="mt-6 text-lg text-neutral-700 dark:text-neutral-300">
          Senior fullstack engineer (8 years in production). I take Laravel /
          PrestaShop / Vue / Flutter apps that already serve real customers and
          bolt on Claude-SDK agents, LLM features, and AI tooling. Without
          rewriting the world.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <a
            href={CALENDLY_URL}
            className="inline-flex items-center rounded-md bg-black px-5 py-3 text-sm font-medium text-white hover:bg-neutral-800 dark:bg-white dark:text-black dark:hover:bg-neutral-200"
          >
            Book a scope call →
          </a>
          <a
            href={`mailto:${EMAIL}`}
            className="inline-flex items-center rounded-md border border-neutral-300 px-5 py-3 text-sm font-medium hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            {EMAIL}
          </a>
        </div>
      </section>

      {/* What I take on */}
      <section className="mb-16">
        <h2 className="mb-6 text-2xl font-semibold">What I take on</h2>
        <div className="grid gap-4 sm:grid-cols-1">
          {ENGAGEMENTS.map((e) => (
            <div
              key={e.title}
              className="rounded-lg border border-neutral-200 p-5 dark:border-neutral-800"
            >
              <h3 className="text-lg font-semibold">{e.title}</h3>
              <p className="mt-1 text-sm text-neutral-500">{e.timeline}</p>
              <p className="mt-3 text-neutral-700 dark:text-neutral-300">{e.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* What I won't take on */}
      <section className="mb-16">
        <h2 className="mb-4 text-2xl font-semibold">What I won&apos;t take on</h2>
        <p className="mb-4 text-sm text-neutral-500">
          Filtering early saves everyone time.
        </p>
        <ul className="space-y-2">
          {WONT_TAKE.map((item) => (
            <li key={item} className="flex gap-3">
              <span className="select-none text-red-500">✕</span>
              <span className="text-neutral-700 dark:text-neutral-300">{item}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* How it works */}
      <section className="mb-16">
        <h2 className="mb-6 text-2xl font-semibold">How it works</h2>
        <ol className="space-y-6">
          {STEPS.map((s) => (
            <li key={s.n} className="flex gap-4">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-black text-sm font-bold text-white dark:bg-white dark:text-black">
                {s.n}
              </span>
              <div>
                <h3 className="font-semibold">{s.title}</h3>
                <p className="mt-1 text-neutral-700 dark:text-neutral-300">{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* FAQ */}
      <section className="mb-16">
        <h2 className="mb-6 text-2xl font-semibold">FAQ</h2>
        <dl className="space-y-4">
          {FAQ.map((f) => (
            <div key={f.q}>
              <dt className="font-semibold">{f.q}</dt>
              <dd className="mt-1 text-neutral-700 dark:text-neutral-300">{f.a}</dd>
            </div>
          ))}
        </dl>
      </section>

      {/* Closing CTA */}
      <section className="rounded-lg bg-neutral-50 p-8 text-center dark:bg-neutral-900">
        <h2 className="text-2xl font-semibold">Sounds like a fit?</h2>
        <p className="mt-3 text-neutral-700 dark:text-neutral-300">
          If none of this fits but you think we should still talk, just email me.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <a
            href={CALENDLY_URL}
            className="inline-flex items-center rounded-md bg-black px-5 py-3 text-sm font-medium text-white hover:bg-neutral-800 dark:bg-white dark:text-black dark:hover:bg-neutral-200"
          >
            Book a scope call →
          </a>
          <a
            href={`mailto:${EMAIL}`}
            className="inline-flex items-center rounded-md border border-neutral-300 px-5 py-3 text-sm font-medium hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            {EMAIL}
          </a>
        </div>
      </section>
    </main>
  );
}
