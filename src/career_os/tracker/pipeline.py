from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..db import Store

# Per-channel non-terminal stages. Order matters — `advance` walks one step
# right unless overridden. Terminal stages are shared (a freelance gig and an
# FT role both end in won/rejected/dropped).
FT_STAGES: tuple[str, ...] = (
    "drafted",    # outreach drafted, not yet sent
    "sent",       # application sent to the company
    "replied",    # got any response from the other side
    "interview",  # scheduled or completed at least one interview
    "offer",      # written offer in hand
)

FREELANCE_STAGES: tuple[str, ...] = (
    "drafted",          # outreach drafted, not yet sent
    "sent",             # pitch sent
    "scope_call",       # scope call scheduled or completed
    "proposal_sent",    # written proposal delivered
    "signed_proposal",  # client signed the proposal — pre-payment / kickoff
)

TERMINAL: tuple[str, ...] = (
    "won",       # signed offer / paid kickoff — terminal success
    "rejected",  # closed by the other side — terminal
    "dropped",   # closed by us — terminal
)

STAGES_BY_CHANNEL: dict[str, tuple[str, ...]] = {
    "ft": FT_STAGES,
    "freelance": FREELANCE_STAGES,
    # An 'either' job (Channel.EITHER) uses the FT pipeline by default —
    # it's the longer / more conservative shape. Promote via --channel if a
    # specific freelance flow emerges.
    "either": FT_STAGES,
}

# Union of every legal stage anywhere — used by the CLI's Choice validator.
ALL_STAGES: tuple[str, ...] = tuple(dict.fromkeys(  # de-dup preserving order
    [*FT_STAGES, *FREELANCE_STAGES, *TERMINAL]
))

# Back-compat: external consumers used to import STAGES as a flat tuple. Keep
# it as the FT-pipeline + terminals (matches the historical shape). New code
# should branch on STAGES_BY_CHANNEL[<channel>] + TERMINAL.
STAGES: tuple[str, ...] = (*FT_STAGES, *TERMINAL)


class StageTransitionError(ValueError):
    pass


def stages_for_channel(channel: str) -> tuple[str, ...]:
    """The full legal stage sequence for an application's channel, including
    terminals. Lookup defaults to FT pipeline for unknown channels."""
    return (*STAGES_BY_CHANNEL.get(channel, FT_STAGES), *TERMINAL)


@dataclass(frozen=True)
class Application:
    job_key: str
    stage: str
    notes: str | None
    applied_at: datetime
    updated_at: datetime
    channel: str = "ft"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_application(
    store: Store, job_key: str, stage: str = "drafted", notes: str | None = None
) -> Application:
    job = store.get_job(job_key)
    if job is None:
        raise StageTransitionError(f"No job with key {job_key!r} — fetch first.")
    channel = job.channel.value
    legal = stages_for_channel(channel)
    if stage not in legal:
        raise StageTransitionError(
            f"Stage {stage!r} is not valid for channel {channel!r}. "
            f"Legal stages: {legal}"
        )
    now = _now()
    with store._conn() as c:  # noqa: SLF001 — same package
        c.execute(
            """
            INSERT INTO applications (job_key, stage, notes, channel, applied_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_key) DO UPDATE SET
                stage=excluded.stage,
                notes=COALESCE(excluded.notes, applications.notes),
                channel=excluded.channel,
                updated_at=excluded.updated_at
            """,
            (job_key, stage, notes, channel, now, now),
        )
    return _get(store, job_key)


def advance(
    store: Store, job_key: str, to: str | None = None, notes: str | None = None
) -> Application:
    app = _get(store, job_key)
    if app is None:
        raise StageTransitionError(
            f"No application for {job_key!r} — record it first with `apply`."
        )
    if app.stage in TERMINAL:
        raise StageTransitionError(
            f"Application is terminal ({app.stage!r}) — cannot advance."
        )
    legal = stages_for_channel(app.channel)
    if to is None:
        i = legal.index(app.stage)
        if i + 1 >= len(legal):
            raise StageTransitionError(f"Already at last stage {app.stage!r}.")
        to = legal[i + 1]
    if to not in legal:
        raise StageTransitionError(
            f"Stage {to!r} is not valid for channel {app.channel!r}. "
            f"Legal stages: {legal}"
        )
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE applications SET stage=?, notes=COALESCE(?, notes), updated_at=? "
            "WHERE job_key=?",
            (to, notes, _now(), job_key),
        )
    return _get(store, job_key)


def funnel_counts(store: Store) -> dict[str, dict[str, int]]:
    """Per-channel funnel counts.

    Returns {"ft": {stage: n, ...}, "freelance": {stage: n, ...}}. Every
    channel has every stage of its own pipeline + the shared terminals
    pre-seeded to 0, so callers can iterate without `.get()` defensiveness.
    """
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT channel, stage, COUNT(*) AS n "
            "FROM applications GROUP BY channel, stage"
        ).fetchall()
    counts: dict[str, dict[str, int]] = {
        "ft": {s: 0 for s in stages_for_channel("ft")},
        "freelance": {s: 0 for s in stages_for_channel("freelance")},
    }
    for row in rows:
        channel = row["channel"] if row["channel"] in counts else "ft"
        counts[channel][row["stage"]] = row["n"]
    return counts


def flat_funnel_counts(store: Store) -> dict[str, int]:
    """Back-compat helper: total counts per stage across channels. Useful
    for the legacy CLI funnel view; new callers should prefer the nested
    `funnel_counts` so FT and freelance pipelines stay distinguishable."""
    nested = funnel_counts(store)
    out: dict[str, int] = {s: 0 for s in ALL_STAGES}
    for channel_counts in nested.values():
        for stage, n in channel_counts.items():
            out[stage] = out.get(stage, 0) + n
    return out


def list_applications(
    store: Store, stage: str | None = None, channel: str | None = None,
) -> list[tuple[Application, str]]:
    sql = (
        "SELECT a.job_key, a.stage, a.notes, a.channel, a.applied_at, "
        "a.updated_at, j.title "
        "FROM applications a JOIN jobs j ON j.key = a.job_key"
    )
    clauses: list[str] = []
    params: list = []
    if stage:
        clauses.append("a.stage = ?")
        params.append(stage)
    if channel:
        clauses.append("a.channel = ?")
        params.append(channel)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY a.updated_at DESC"
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(sql, tuple(params)).fetchall()
    return [(_row_to_app(r), r["title"]) for r in rows]


def _get(store: Store, job_key: str) -> Application | None:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT job_key, stage, notes, channel, applied_at, updated_at "
            "FROM applications WHERE job_key=?",
            (job_key,),
        ).fetchone()
    return _row_to_app(row) if row else None


def _row_to_app(row) -> Application:
    # `channel` column was added by a Tier 3 migration; rows from older code
    # paths in tests may not have it. Default to 'ft' (the pre-migration
    # behavior) so back-compat tests don't crash.
    row_dict = dict(row)
    return Application(
        job_key=row["job_key"],
        stage=row["stage"],
        notes=row["notes"],
        channel=row_dict.get("channel") or "ft",
        applied_at=datetime.fromisoformat(row["applied_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
