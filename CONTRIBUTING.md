# Contributing to Career-OS

Career-OS is built in public as the toolchain Bakhouche Akram uses to run his
own job search + freelance pipeline + online presence. PRs and issues are
welcome — the codebase is deliberately small so new contributors can read
the whole thing in one sitting.

## Architecture at a glance

```
fetch  →  store  →  score  →  draft  →  digest
(scrapers)        (Claude SDK)  (Claude SDK)
```

Each stage is one Python module:

| Module | Responsibility |
|--------|---------------|
| `src/career_os/scrapers/` | One file per source. Async generator yielding `JobPost` models. |
| `src/career_os/db/store.py` | SQLite-backed store with Postgres-shaped schema. |
| `src/career_os/scorer/claude_scorer.py` | Prompt-cached Claude call → structured `Score`. |
| `src/career_os/drafter/outreach.py` | Scored job + profile → ready-to-send outreach. |
| `src/career_os/digest/render.py` | Top-N matches → Markdown digest. |
| `src/career_os/cli/main.py` | The `career-os` CLI binding it all together. |

## Adding a new scraper (the easy on-ramp)

1. Add `src/career_os/scrapers/<your_source>.py` with a `class FooScraper(Scraper)` exposing:
   - `key: ClassVar[str]` — the unique CLI key
   - `async def fetch(self, client: httpx.AsyncClient) -> AsyncIterator[JobPost]`
2. Add it to `REGISTRY` in `src/career_os/scrapers/registry.py`.
3. Add a test in `tests/` covering at least one happy-path parse.
4. Run `career-os fetch --source <your_key>` to live-validate.

Scrapers should:
- Set `channel=Channel.FREELANCE` when the source is freelance-specific (HN freelancer thread, Contra, Upwork, etc.)
- Use `Channel.FT` for traditional job boards (RemoteOK, WeWorkRemotely, etc.)
- Use `Channel.EITHER` when the source mixes both and the post itself doesn't tell you which

## Running tests

```bash
pip install -e ".[dev]"
pytest -q
python scripts/smoke.py
ruff check src tests
```

CI runs all of the above on Python 3.11 and 3.12.

## Profile + prompts

The profile lives in `src/career_os/profile.py` — that's the default applied
to every score. Fork the file (or set it via the future `--profile` flag) to
score against your own background.

The scorer + drafter system prompts live next to their code, not in a separate
"prompts" directory. They are documented inline and intentionally treated as
load-bearing source — change them with the same care as any other module,
and add an eval if you do.

## Roadmap

See `README.md` "Phases" section. Short version:
- Phase 1 (current) — crawler + scorer + drafter
- Phase 2 — application-pipeline tracker, Postgres swap-in
- Phase 3 — presence module (cross-poster)
- Phase 4 — GitHub optimizer + public launch

## License

MIT. See `LICENSE`.
