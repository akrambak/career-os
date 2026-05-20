"""Automations layer — cron-style scheduling on top of Career-OS internals.

An automation is a named row in `automations` (e.g. `fetch_hourly`) that
maps to a registered handler. The runtime:

  1. Selects armed rows whose `next_run_due_at <= now`.
  2. Calls the handler.
  3. Records start/finish + status to `automation_runs`.
  4. Bumps `next_run_due_at` by `interval_minutes`.

Handlers are pure callables — they take `(store, config)` and return a
`HandlerResult`. The runtime owns persistence and scheduling. This
separation means handlers can be unit-tested without going near the
schedule logic.

`career-os automations run-due` drives the runtime from cron. The
dashboard's Automations page exposes arm/disarm + "Run now".
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..db import Store

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Automation:
    id: int
    name: str
    kind: str
    interval_minutes: int
    config: dict
    is_armed: bool
    last_run_at: datetime | None
    next_run_due_at: datetime | None
    last_status: str | None
    last_summary: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AutomationRun:
    id: int
    automation_id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    summary: str | None
    error_detail: str | None


@dataclass(frozen=True)
class HandlerResult:
    status: str            # 'ok' | 'failed' | 'skipped'
    summary: str           # human-readable one-liner
    error_detail: str | None = None


# ---- handler registry ----------------------------------------------------

# Handlers are sync callables `(store, config) -> HandlerResult`. Async
# handlers wrap themselves with `asyncio.run(...)` internally so the
# scheduling runtime stays straightforward.

HandlerFn = Callable[[Store, dict], HandlerResult]
_HANDLERS: dict[str, HandlerFn] = {}


def register_handler(kind: str):
    """Decorator: register a handler callable under a `kind` key."""
    def deco(fn: HandlerFn) -> HandlerFn:
        _HANDLERS[kind] = fn
        return fn
    return deco


def known_kinds() -> list[str]:
    return sorted(_HANDLERS)


# ---- built-in handlers ---------------------------------------------------

@register_handler("fetch")
def _h_fetch(store: Store, config: dict) -> HandlerResult:
    from ..crawler import crawl
    keys = config.get("sources") or None
    use_watermarks = bool(config.get("use_watermarks", True))
    results = asyncio.run(crawl(store, keys, use_watermarks=use_watermarks))
    new = sum(results.values())
    return HandlerResult("ok", f"{new} new across {len(results)} source(s)")


@register_handler("score")
def _h_score(store: Store, config: dict) -> HandlerResult:
    from ..config import Settings
    from ..profile import DEFAULT_PROFILE
    from ..scorer import ClaudeScorer, score_pending
    settings = Settings.load()
    if not settings.anthropic_api_key:
        return HandlerResult("skipped", "ANTHROPIC_API_KEY not set")
    limit = int(config.get("limit", 50))
    scorer = ClaudeScorer(settings.anthropic_api_key)
    try:
        n = score_pending(store, scorer, DEFAULT_PROFILE, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return HandlerResult("failed", "score_pending raised", str(exc))
    return HandlerResult("ok", f"scored {n} job(s)")


@register_handler("run_action_generators")
def _h_run_action_generators(store: Store, config: dict) -> HandlerResult:
    from ..actions import run_generators
    counts = run_generators(store)
    n = sum(counts.values())
    return HandlerResult("ok", f"{n} actions touched across {len(counts)} generators")


@register_handler("recheck")
def _h_recheck(store: Store, config: dict) -> HandlerResult:
    from ..recheck import recheck as run_recheck
    from ..recheck import summarize
    limit = int(config.get("limit", 200))
    max_age = int(config.get("max_age_days", 7))
    try:
        outcomes = asyncio.run(run_recheck(
            store, limit=limit, max_age_days=max_age,
        ))
    except Exception as exc:  # noqa: BLE001
        return HandlerResult("failed", "recheck raised", str(exc))
    s = summarize(outcomes)
    return HandlerResult(
        "ok", f"kept {s.get('kept',0)} · closed {s.get('closed',0)} · "
              f"transient {s.get('transient',0)}",
    )


@register_handler("scan_trends")
def _h_scan_trends(store: Store, config: dict) -> HandlerResult:
    from ..profile import DEFAULT_PROFILE
    from ..trends.sources import scan_sources
    sources = config.get("sources") or None
    try:
        results = asyncio.run(scan_sources(
            store, DEFAULT_PROFILE, sources=sources,
        ))
    except Exception as exc:  # noqa: BLE001
        return HandlerResult("failed", "scan_sources raised", str(exc))
    n = sum(results.values())
    breakdown = ", ".join(f"{k}:{v}" for k, v in results.items()) or "—"
    return HandlerResult("ok", f"{n} trends touched ({breakdown})")


@register_handler("digest_email")
def _h_digest(store: Store, config: dict) -> HandlerResult:
    from datetime import date

    from ..config import Settings
    from ..digest import DigestEmailer, render_digest
    settings = Settings.load()
    if not settings.smtp_provider or not settings.smtp_api_key:
        return HandlerResult("skipped", "SMTP_PROVIDER + SMTP_API_KEY not set")
    limit = int(config.get("limit", 5))
    min_fit = int(config.get("min_fit", 65))
    rows = store.top_scored(limit=limit, min_fit=min_fit)
    md = render_digest(rows)
    emailer = DigestEmailer(
        provider=settings.smtp_provider, api_key=settings.smtp_api_key,
        sender=settings.smtp_from, recipient=settings.smtp_to,
    )
    result = emailer.send(
        subject=f"Top {len(rows)} matches — {date.today().isoformat()}",
        markdown_body=md,
    )
    if result.ok:
        return HandlerResult("ok", f"sent via {result.provider}: {result.detail}")
    return HandlerResult("failed", f"send failed via {result.provider}", result.detail)


# ---- default automation rows (seeded once) -------------------------------

DEFAULT_AUTOMATIONS: tuple[tuple[str, str, int, dict, bool], ...] = (
    # (name, kind, interval_minutes, config, is_armed)
    ("fetch_hourly", "fetch", 60, {}, True),
    ("score_after_fetch", "score", 90, {"limit": 50}, False),
    ("inbox_generators_15min", "run_action_generators", 15, {}, True),
    ("recheck_weekly", "recheck", 60 * 24 * 7, {"max_age_days": 7}, False),
    ("digest_daily", "digest_email", 60 * 24, {"limit": 5, "min_fit": 65}, False),
    ("scan_trends_4h", "scan_trends", 60 * 4, {"sources": ["hn", "devto"]}, True),
)


def seed_defaults(store: Store) -> int:
    """Insert any missing default automations. Returns count inserted.
    Idempotent — never clobbers user-edited rows."""
    inserted = 0
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        for name, kind, interval, config, armed in DEFAULT_AUTOMATIONS:
            existing = c.execute(
                "SELECT 1 FROM automations WHERE name = ?", (name,),
            ).fetchone()
            if existing:
                continue
            c.execute(
                """
                INSERT INTO automations
                    (name, kind, interval_minutes, config, is_armed,
                     next_run_due_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, kind, interval, json.dumps(config), 1 if armed else 0,
                 now, now, now),
            )
            inserted += 1
    return inserted


# ---- CRUD ----------------------------------------------------------------

def list_automations(store: Store) -> list[Automation]:
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT * FROM automations ORDER BY name",
        ).fetchall()
    return [_row_to_automation(r) for r in rows]


def get_by_name(store: Store, name: str) -> Automation | None:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT * FROM automations WHERE name = ?", (name,),
        ).fetchone()
    return _row_to_automation(row) if row else None


def set_armed(store: Store, name: str, armed: bool) -> Automation:
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE automations SET is_armed = ?, updated_at = ? WHERE name = ?",
            (1 if armed else 0, now, name),
        )
    a = get_by_name(store, name)
    if a is None:
        raise LookupError(f"automation {name!r} not found")
    return a


def update_config(store: Store, name: str, *,
                  interval_minutes: int | None = None,
                  config: dict | None = None) -> Automation:
    fields: list[str] = []
    params: list = []
    if interval_minutes is not None:
        fields.append("interval_minutes = ?")
        params.append(int(interval_minutes))
    if config is not None:
        fields.append("config = ?")
        params.append(json.dumps(config))
    if not fields:
        return get_by_name(store, name)
    fields.append("updated_at = ?")
    params.append(_now())
    params.append(name)
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            f"UPDATE automations SET {', '.join(fields)} WHERE name = ?",
            tuple(params),
        )
    return get_by_name(store, name)


def list_runs(store: Store, name: str, limit: int = 20) -> list[AutomationRun]:
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT r.* FROM automation_runs r
            JOIN automations a ON a.id = r.automation_id
            WHERE a.name = ?
            ORDER BY r.started_at DESC
            LIMIT ?
            """,
            (name, limit),
        ).fetchall()
    return [_row_to_run(r) for r in rows]


# ---- runtime -------------------------------------------------------------

def fire(store: Store, name: str) -> HandlerResult:
    """Run one automation by name unconditionally (manual 'Run now' button).
    Records to automation_runs + updates the parent row."""
    auto = get_by_name(store, name)
    if auto is None:
        raise LookupError(f"automation {name!r} not found")
    handler = _HANDLERS.get(auto.kind)
    if handler is None:
        result = HandlerResult("failed", f"no handler registered for kind {auto.kind!r}")
    else:
        result = _execute(store, auto, handler)
    return result


def run_due(store: Store, *, now: datetime | None = None) -> dict[str, HandlerResult]:
    """Run every armed automation whose `next_run_due_at <= now`. Returns
    {name: result}. Safe to call from cron — overlapping invocations only
    re-fire genuinely-due rows."""
    cutoff = (now or datetime.now(UTC)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT name FROM automations WHERE is_armed = 1 AND "
            "(next_run_due_at IS NULL OR next_run_due_at <= ?) "
            "ORDER BY next_run_due_at NULLS FIRST",
            (cutoff,),
        ).fetchall()
    out: dict[str, HandlerResult] = {}
    for r in rows:
        out[r["name"]] = fire(store, r["name"])
    return out


def _execute(
    store: Store, auto: Automation, handler: HandlerFn,
) -> HandlerResult:
    started = _now()
    try:
        result = handler(store, auto.config)
    except Exception as exc:  # noqa: BLE001 — handler errors are recorded, not raised
        logger.exception("automation %s handler raised", auto.name)
        result = HandlerResult(
            "failed", f"{type(exc).__name__}: {exc}", str(exc)[:1000],
        )
    finished = _now()
    next_due = (
        datetime.now(UTC) + timedelta(minutes=auto.interval_minutes)
    ).isoformat()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            """
            INSERT INTO automation_runs
                (automation_id, started_at, finished_at, status, summary,
                 error_detail)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (auto.id, started, finished, result.status, result.summary,
             result.error_detail),
        )
        c.execute(
            "UPDATE automations SET last_run_at = ?, last_status = ?, "
            "last_summary = ?, next_run_due_at = ?, updated_at = ? "
            "WHERE id = ?",
            (finished, result.status, result.summary, next_due, finished, auto.id),
        )
    return result


# ---- internals ----------------------------------------------------------

def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso_or_none(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _row_to_automation(row) -> Automation:
    return Automation(
        id=row["id"], name=row["name"], kind=row["kind"],
        interval_minutes=int(row["interval_minutes"]),
        config=json.loads(row["config"] or "{}"),
        is_armed=bool(row["is_armed"]),
        last_run_at=_iso_or_none(row["last_run_at"]),
        next_run_due_at=_iso_or_none(row["next_run_due_at"]),
        last_status=row["last_status"],
        last_summary=row["last_summary"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_run(row) -> AutomationRun:
    return AutomationRun(
        id=row["id"], automation_id=row["automation_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=_iso_or_none(row["finished_at"]),
        status=row["status"], summary=row["summary"],
        error_detail=row["error_detail"],
    )


__all__ = [
    "Automation", "AutomationRun", "HandlerResult",
    "register_handler", "known_kinds",
    "DEFAULT_AUTOMATIONS", "seed_defaults",
    "list_automations", "get_by_name", "set_armed", "update_config", "list_runs",
    "fire", "run_due",
]
