"""HITL (human-in-the-loop) action inbox.

Every automation that wants the user's attention writes a row into the
`actions` table via this module. The user resolves rows from the Inbox
dashboard page with approve / dismiss / defer / snooze. Generators are
idempotent — the `UNIQUE(kind, target_kind, target_id)` constraint stops
re-runs from duplicating an open action.

Design:
  - The "what to suggest" lives in `generators.py` (one fn per action kind).
  - The "how to persist" lives here.
  - Both are UI-free — pages call them; nothing imports streamlit.

Action kinds (extend as features grow):
  - 'review_job'           : a high-fit job is unscored or undrafted
  - 'send_draft'           : a draft exists but no application was recorded
  - 'follow_up'            : an application is stuck >N days at the same stage
  - 'review_post'          : a post is status='ready' and awaiting publish
  - 'recheck_stale_source' : a source hasn't yielded jobs in N days
  - 'kpi_alert'            : a tracked KPI crossed a threshold
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from ..db import Store

# Severity levels — used by the inbox UI to colorize + sort.
SEVERITIES = ("urgent", "normal", "low")
STATUSES = ("open", "approved", "dismissed", "deferred", "snoozed")


@dataclass(frozen=True)
class Action:
    id: int
    kind: str
    title: str
    description: str | None
    severity: str
    target_kind: str | None
    target_id: str | None
    payload: dict
    status: str
    snoozed_until: datetime | None
    resolved_at: datetime | None
    resolved_note: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def is_open(self) -> bool:
        return self.status == "open" or (
            self.status == "snoozed"
            and (self.snoozed_until is None or self.snoozed_until <= datetime.now(UTC))
        )


# ---- CRUD ----------------------------------------------------------------

def _now() -> str:
    return datetime.now(UTC).isoformat()


def upsert_action(
    store: Store, *,
    kind: str, title: str,
    target_kind: str | None = None, target_id: str | None = None,
    description: str | None = None, severity: str = "normal",
    payload: dict | None = None,
) -> Action:
    """Idempotent insert. If the (kind, target_kind, target_id) tuple
    already has an OPEN action, we update its title/description/payload in
    place. If it has a RESOLVED action, we don't re-open — that's the
    user's explicit decision; resolved actions stay resolved.

    Returns the resulting Action (open or resolved).
    """
    if severity not in SEVERITIES:
        raise ValueError(f"unknown severity {severity!r}")
    now = _now()
    payload_json = json.dumps(payload or {})
    with store._conn() as c:  # noqa: SLF001
        existing = c.execute(
            "SELECT id, status FROM actions "
            "WHERE kind = ? AND target_kind IS ? AND target_id IS ?",
            (kind, target_kind, target_id),
        ).fetchone()
        if existing:
            target_id_int = existing["id"]
            if existing["status"] == "open":
                c.execute(
                    "UPDATE actions SET title=?, description=?, severity=?, "
                    "payload=?, updated_at=? WHERE id=?",
                    (title, description, severity, payload_json, now, target_id_int),
                )
        else:
            c.execute(
                """
                INSERT INTO actions (kind, title, description, severity,
                                     target_kind, target_id, payload,
                                     status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
                """,
                (kind, title, description, severity, target_kind, target_id,
                 payload_json, now, now),
            )
            target_id_int = c.execute(
                "SELECT last_insert_rowid() AS id"
            ).fetchone()["id"]
    # Read AFTER the with-block commits — a fresh connection would otherwise
    # see stale state.
    return _get(store, target_id_int)


def list_actions(
    store: Store, *,
    status: str | None = "open",
    kind: str | None = None,
    severity: str | None = None,
    include_snoozed_due: bool = True,
) -> list[Action]:
    """List actions. Default behaviour returns OPEN actions only. If
    `include_snoozed_due=True` (the default), rows in status='snoozed' whose
    snoozed_until has passed are returned alongside open ones — they're
    effectively re-surfaced.
    """
    now = _now()
    sql_parts = ["SELECT * FROM actions WHERE 1=1"]
    params: list = []
    if status == "open" and include_snoozed_due:
        sql_parts.append(
            "AND (status = 'open' OR (status = 'snoozed' AND "
            "(snoozed_until IS NULL OR snoozed_until <= ?)))"
        )
        params.append(now)
    elif status:
        sql_parts.append("AND status = ?")
        params.append(status)
    if kind:
        sql_parts.append("AND kind = ?")
        params.append(kind)
    if severity:
        sql_parts.append("AND severity = ?")
        params.append(severity)
    sql_parts.append(
        "ORDER BY CASE severity "
        "    WHEN 'urgent' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, "
        "    updated_at DESC"
    )
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(" ".join(sql_parts), tuple(params)).fetchall()
    return [_row_to_action(r) for r in rows]


def resolve(
    store: Store, action_id: int, status: str, note: str | None = None,
) -> Action:
    """Approve / dismiss / defer an action. Terminal — sets resolved_at."""
    if status not in ("approved", "dismissed", "deferred"):
        raise ValueError(f"resolve status must be approved/dismissed/deferred, got {status!r}")
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE actions SET status=?, resolved_at=?, resolved_note=?, "
            "updated_at=? WHERE id=?",
            (status, now, note, now, action_id),
        )
    return _get(store, action_id)


def snooze(store: Store, action_id: int, until: datetime) -> Action:
    """Hide an action until a future timestamp. Re-surfaces automatically."""
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE actions SET status='snoozed', snoozed_until=?, updated_at=? "
            "WHERE id=?",
            (until.isoformat(), now, action_id),
        )
    return _get(store, action_id)


def counts_by_severity(store: Store) -> dict[str, int]:
    """Headline counts for the dashboard banner."""
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT severity, COUNT(*) AS n FROM actions
            WHERE status = 'open' OR (status = 'snoozed' AND
                  (snoozed_until IS NULL OR snoozed_until <= ?))
            GROUP BY severity
            """,
            (now,),
        ).fetchall()
    counts = {s: 0 for s in SEVERITIES}
    for r in rows:
        counts[r["severity"]] = int(r["n"])
    return counts


def purge_resolved(store: Store, older_than_days: int = 90) -> int:
    """House-keeping: drop resolved actions older than N days. Returns rows
    deleted. Manual — call from a CLI or admin button."""
    from datetime import timedelta
    cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        cur = c.execute(
            "DELETE FROM actions WHERE status IN ('approved','dismissed','deferred') "
            "AND resolved_at < ?",
            (cutoff,),
        )
        return cur.rowcount


# ---- generators ----------------------------------------------------------

def gen_review_high_fit_jobs(
    store: Store, *, fit_threshold: int = 75, limit: int = 25,
) -> list[Action]:
    """High-fit scored job exists but no draft yet → review_job action."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT j.key, j.title, j.company, j.channel, s.fit, s.suggested_angle
            FROM jobs j JOIN scores s ON s.job_key = j.key
            LEFT JOIN drafts d ON d.job_key = j.key
            WHERE s.fit >= ? AND d.job_key IS NULL AND j.is_closed = 0
            ORDER BY s.fit DESC, j.fetched_at DESC
            LIMIT ?
            """,
            (fit_threshold, limit),
        ).fetchall()
    created: list[Action] = []
    for r in rows:
        severity = "urgent" if int(r["fit"]) >= 85 else "normal"
        created.append(upsert_action(
            store,
            kind="review_job",
            title=f"[{r['fit']}] {r['title']} — {r['company'] or 'Unknown'}",
            description=r["suggested_angle"] or "Review for fit and draft outreach.",
            severity=severity,
            target_kind="job", target_id=r["key"],
            payload={"fit": int(r["fit"]), "channel": r["channel"]},
        ))
    return created


def gen_send_drafts(store: Store, *, limit: int = 25) -> list[Action]:
    """Draft exists but no application logged → send_draft action."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT d.job_key, j.title, j.company, j.channel, j.is_closed,
                   COALESCE(s.fit, 0) AS fit
            FROM drafts d JOIN jobs j ON j.key = d.job_key
            LEFT JOIN scores s ON s.job_key = d.job_key
            LEFT JOIN applications a ON a.job_key = d.job_key
            WHERE a.job_key IS NULL AND j.is_closed = 0
            ORDER BY s.fit DESC, d.drafted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    created: list[Action] = []
    for r in rows:
        created.append(upsert_action(
            store,
            kind="send_draft",
            title=f"Send draft: {r['title']} — {r['company'] or 'Unknown'}",
            description=f"Drafted but never sent. Fit {r['fit']}.",
            severity="normal" if int(r["fit"]) < 80 else "urgent",
            target_kind="job", target_id=r["job_key"],
            payload={"fit": int(r["fit"]), "channel": r["channel"]},
        ))
    return created


def gen_stale_applications(
    store: Store, *, days: int = 7, limit: int = 25,
) -> list[Action]:
    """An application has been in the same non-terminal stage for >N days."""
    from datetime import timedelta
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT a.job_key, a.stage, a.channel, j.title, j.company, a.updated_at
            FROM applications a JOIN jobs j ON j.key = a.job_key
            WHERE a.stage NOT IN ('won','rejected','dropped')
              AND a.updated_at < ?
            ORDER BY a.updated_at ASC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    created: list[Action] = []
    for r in rows:
        days_stuck = (
            datetime.now(UTC) - datetime.fromisoformat(r["updated_at"])
        ).days
        created.append(upsert_action(
            store,
            kind="follow_up",
            title=f"Stale {days_stuck}d: {r['title']} ({r['stage']})",
            description=(
                f"No movement on {r['channel']} application at stage "
                f"{r['stage']!r} for {days_stuck} days. Send a follow-up?"
            ),
            severity="normal",
            target_kind="application", target_id=r["job_key"],
            payload={"stage": r["stage"], "channel": r["channel"], "days": days_stuck},
        ))
    return created


def gen_unlinked_mentions(
    store: Store, *, limit: int = 25,
) -> list[Action]:
    """Open mentions with has_link=0 → unlinked_mention action.
    Severity = urgent when the source is hn (highest-DA on average)."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT id, source, source_url, matched_term, context_snippet
            FROM mentions
            WHERE status = 'open' AND has_link = 0
            ORDER BY discovered_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    created: list[Action] = []
    for r in rows:
        severity = "urgent" if r["source"] == "hn" else "normal"
        snippet = (r["context_snippet"] or "")[:120]
        created.append(upsert_action(
            store,
            kind="unlinked_mention",
            title=f"Unlinked mention on {r['source']}: {r['matched_term']}",
            description=(
                f"{snippet} — convert to backlink (already linked there?) "
                "or spawn an outreach to ask for the link added."
            ),
            severity=severity,
            target_kind="mention", target_id=str(r["id"]),
            payload={
                "source": r["source"], "source_url": r["source_url"],
                "matched_term": r["matched_term"],
            },
        ))
    return created


def gen_stale_outreach(
    store: Store, *, days: int = 10, limit: int = 25,
) -> list[Action]:
    """Outreach targets stuck in stage='pitched' for >N days → stale_pitch."""
    from datetime import timedelta
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT id, name, site_domain, category, value_score, pitched_at
            FROM outreach_targets
            WHERE stage = 'pitched' AND pitched_at IS NOT NULL
              AND pitched_at < ?
            ORDER BY value_score DESC, pitched_at ASC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    created: list[Action] = []
    for r in rows:
        pitched = datetime.fromisoformat(r["pitched_at"])
        days_stale = (datetime.now(UTC) - pitched).days
        value = int(r["value_score"])
        severity = "urgent" if value >= 8 else "normal"
        created.append(upsert_action(
            store,
            kind="stale_pitch",
            title=f"Stale {days_stale}d: {r['name']} ({r['category']})",
            description=(
                f"Pitched {days_stale} days ago, no reply logged. "
                f"Follow up, or mark declined/dropped."
            ),
            severity=severity,
            target_kind="outreach_target", target_id=str(r["id"]),
            payload={
                "category": r["category"], "value_score": value,
                "days_stale": days_stale, "site_domain": r["site_domain"],
            },
        ))
    return created


def gen_dead_backlinks(
    store: Store, *, min_da_for_urgent: int = 40, limit: int = 25,
) -> list[Action]:
    """Backlinks newly flipped to dead/removed → dead_backlink action.
    Severity = urgent if the source domain had DA ≥ threshold."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT id, source_url, source_domain, target_url, anchor_text,
                   rel, status, da_estimate
            FROM backlinks
            WHERE status IN ('dead', 'removed')
            ORDER BY last_checked_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    created: list[Action] = []
    for r in rows:
        da = int(r["da_estimate"] or 0)
        severity = "urgent" if da >= min_da_for_urgent else "normal"
        host = r["source_domain"] or "(unknown)"
        created.append(upsert_action(
            store,
            kind="dead_backlink",
            title=f"Lost link from {host} ({r['status']})",
            description=(
                f"{r['rel']} link → {r['target_url']}. "
                f"Reach out to the publisher or find a replacement URL."
            ),
            severity=severity,
            target_kind="backlink", target_id=str(r["id"]),
            payload={
                "source_url": r["source_url"], "target_url": r["target_url"],
                "anchor_text": r["anchor_text"], "rel": r["rel"],
                "status": r["status"], "da_estimate": da,
            },
        ))
    return created


def gen_high_signal_trends(
    store: Store, *, signal_threshold: float = 2.5, limit: int = 10,
) -> list[Action]:
    """A trend's signal_score crossed the threshold and we haven't used it
    for a post yet → review_trend action."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            """
            SELECT id, source, title, signal_score, url
            FROM trends
            WHERE signal_score >= ? AND used_at IS NULL
            ORDER BY signal_score DESC
            LIMIT ?
            """,
            (signal_threshold, limit),
        ).fetchall()
    created: list[Action] = []
    for r in rows:
        sig = float(r["signal_score"])
        severity = "urgent" if sig >= 4.0 else "normal"
        created.append(upsert_action(
            store,
            kind="review_trend",
            title=f"[{sig:.1f}] {r['title']}",
            description=(
                f"High-signal {r['source']} trend. Generate a post from "
                f"the Trends page if it fits your voice."
            ),
            severity=severity,
            target_kind="trend", target_id=str(r["id"]),
            payload={
                "signal_score": sig, "source": r["source"], "url": r["url"],
            },
        ))
    return created


def gen_publish_ready_posts(store: Store, *, limit: int = 25) -> list[Action]:
    """Post is status='ready' but hasn't been published → review_post."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT id, title, channel FROM posts WHERE status = 'ready' "
            "AND posted_at IS NULL ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    created: list[Action] = []
    for r in rows:
        created.append(upsert_action(
            store,
            kind="review_post",
            title=f"Publish: {r['title']} ({r['channel']})",
            description="Marked ready — review one more time, then publish.",
            severity="normal",
            target_kind="post", target_id=str(r["id"]),
            payload={"channel": r["channel"]},
        ))
    return created


# All generators in run-order. Each is a callable taking `store`.
GENERATORS: tuple = (
    ("review_high_fit_jobs", gen_review_high_fit_jobs),
    ("send_drafts", gen_send_drafts),
    ("stale_applications", gen_stale_applications),
    ("publish_ready_posts", gen_publish_ready_posts),
    ("high_signal_trends", gen_high_signal_trends),
    ("dead_backlinks", gen_dead_backlinks),
    ("stale_outreach", gen_stale_outreach),
    ("unlinked_mentions", gen_unlinked_mentions),
)


def run_generators(
    store: Store, names: Iterable[str] | None = None,
) -> dict[str, int]:
    """Run every (or selected) generator. Returns per-generator action count
    created/touched. Existing OPEN actions are refreshed in place; resolved
    actions are not re-opened."""
    selected = set(names) if names else None
    out: dict[str, int] = {}
    for name, fn in GENERATORS:
        if selected and name not in selected:
            continue
        out[name] = len(fn(store))
    return out


# ---- internals ----------------------------------------------------------

def _get(store: Store, action_id: int) -> Action:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT * FROM actions WHERE id = ?", (action_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"action {action_id} not found")
    return _row_to_action(row)


def _row_to_action(row) -> Action:
    return Action(
        id=row["id"],
        kind=row["kind"],
        title=row["title"],
        description=row["description"],
        severity=row["severity"],
        target_kind=row["target_kind"],
        target_id=row["target_id"],
        payload=json.loads(row["payload"] or "{}"),
        status=row["status"],
        snoozed_until=(
            datetime.fromisoformat(row["snoozed_until"])
            if row["snoozed_until"] else None
        ),
        resolved_at=(
            datetime.fromisoformat(row["resolved_at"])
            if row["resolved_at"] else None
        ),
        resolved_note=row["resolved_note"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


__all__ = [
    "SEVERITIES", "STATUSES", "GENERATORS",
    "Action",
    "upsert_action", "list_actions", "resolve", "snooze",
    "counts_by_severity", "purge_resolved",
    "gen_review_high_fit_jobs", "gen_send_drafts",
    "gen_stale_applications", "gen_publish_ready_posts",
    "gen_high_signal_trends",
    "gen_dead_backlinks",
    "gen_stale_outreach",
    "gen_unlinked_mentions",
    "run_generators",
]
