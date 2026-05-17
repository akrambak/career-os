"""Import smoke test — fails loudly if any module is broken."""
from __future__ import annotations

import importlib

MODULES = [
    "career_os",
    "career_os.config",
    "career_os.models",
    "career_os.profile",
    "career_os.db",
    "career_os.db.store",
    "career_os.crawler",
    "career_os.crawler.run",
    "career_os.scorer",
    "career_os.scorer.claude_scorer",
    "career_os.drafter",
    "career_os.drafter.outreach",
    "career_os.digest",
    "career_os.digest.render",
    "career_os.digest.email",
    "career_os.tracker",
    "career_os.tracker.pipeline",
    "career_os.eval",
    "career_os.eval.scorer_eval",
    "career_os.scrapers",
    "career_os.scrapers.base",
    "career_os.scrapers.remoteok",
    "career_os.scrapers.weworkremotely",
    "career_os.scrapers.remotive",
    "career_os.scrapers.hn_freelancer",
    "career_os.scrapers.hn_whoishiring",
    "career_os.dashboard.queries",
    "career_os.dashboard.network",
    "career_os.dashboard.todos",
    "career_os.dashboard.plan",
    "career_os.cli.main",
]


def main() -> None:
    failed: list[tuple[str, Exception]] = []
    for m in MODULES:
        try:
            importlib.import_module(m)
            print(f"  ok  {m}")
        except Exception as exc:  # noqa: BLE001
            failed.append((m, exc))
            print(f"  FAIL {m} — {exc}")
    if failed:
        raise SystemExit(1)
    print(f"\nAll {len(MODULES)} modules import cleanly.")


if __name__ == "__main__":
    main()
