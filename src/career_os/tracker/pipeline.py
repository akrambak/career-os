from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..db import Store

# Stage order matters — `advance` walks one step right unless overridden.
STAGES: tuple[str, ...] = (
    "drafted",   # outreach drafted, not yet sent
    "sent",      # message / application sent to the company
    "replied",   # got a response — anything from "no thanks" to "let's chat"
    "interview", # scheduled or completed at least one interview / scope call
    "offer",     # offer received (FT) or proposal accepted (freelance)
    "won",       # signed offer / contract — terminal success
    "rejected",  # closed by other side — terminal
    "dropped",   # closed by us (lost interest, fit fell apart) — terminal
)

TERMINAL = {"won", "rejected", "dropped"}


class StageTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class Application:
    job_key: str
    stage: str
    notes: str | None
    applied_at: datetime
    updated_at: datetime


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record_application(
    store: Store, job_key: str, stage: str = "drafted", notes: str | None = None
) -> Application:
    if stage not in STAGES:
        raise StageTransitionError(f"Unknown stage {stage!r}. Known: {STAGES}")
    if store.get_job(job_key) is None:
        raise StageTransitionError(f"No job with key {job_key!r} — fetch first.")
    now = _now()
    with store._conn() as c:  # noqa: SLF001 — same package
        c.execute(
            """
            INSERT INTO applications (job_key, stage, notes, applied_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_key) DO UPDATE SET
                stage=excluded.stage,
                notes=COALESCE(excluded.notes, applications.notes),
                updated_at=excluded.updated_at
            """,
            (job_key, stage, notes, now, now),
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
    if to is None:
        i = STAGES.index(app.stage)
        if i + 1 >= len(STAGES):
            raise StageTransitionError(f"Already at last stage {app.stage!r}.")
        to = STAGES[i + 1]
    if to not in STAGES:
        raise StageTransitionError(f"Unknown stage {to!r}. Known: {STAGES}")
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE applications SET stage=?, notes=COALESCE(?, notes), updated_at=? "
            "WHERE job_key=?",
            (to, notes, _now(), job_key),
        )
    return _get(store, job_key)


def funnel_counts(store: Store) -> dict[str, int]:
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT stage, COUNT(*) AS n FROM applications GROUP BY stage"
        ).fetchall()
    counts = {s: 0 for s in STAGES}
    for row in rows:
        counts[row["stage"]] = row["n"]
    return counts


def list_applications(
    store: Store, stage: str | None = None
) -> list[tuple[Application, str]]:
    sql = (
        "SELECT a.job_key, a.stage, a.notes, a.applied_at, a.updated_at, j.title "
        "FROM applications a JOIN jobs j ON j.key = a.job_key"
    )
    params: tuple = ()
    if stage:
        sql += " WHERE a.stage = ?"
        params = (stage,)
    sql += " ORDER BY a.updated_at DESC"
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(sql, params).fetchall()
    return [(_row_to_app(r), r["title"]) for r in rows]


def _get(store: Store, job_key: str) -> Application | None:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT job_key, stage, notes, applied_at, updated_at "
            "FROM applications WHERE job_key=?",
            (job_key,),
        ).fetchone()
    return _row_to_app(row) if row else None


def _row_to_app(row) -> Application:
    return Application(
        job_key=row["job_key"],
        stage=row["stage"],
        notes=row["notes"],
        applied_at=datetime.fromisoformat(row["applied_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
