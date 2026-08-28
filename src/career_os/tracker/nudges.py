"""Follow-up nudges — surface applications that have gone quiet so the ball
in the other side's court doesn't rot. UI-free so it's unit-testable."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ..db import Store
from .pipeline import TERMINAL, Application, _row_to_app

# What to actually do when an application in a given stage goes stale. Keyed by
# stage; the ball is in our court for 'drafted' (never sent) and in theirs for
# everything downstream (silence → send a follow-up).
SUGGESTION_BY_STAGE: dict[str, str] = {
    "drafted": "Drafted but never sent — send it or drop it.",
    "sent": "No reply — send a short follow-up.",
    "replied": "Thread stalled — re-engage and propose a next step.",
    "interview": "Post-interview — thank them and ask about next steps.",
    "offer": "Offer outstanding — respond or negotiate before it lapses.",
    "scope_call": "Follow up on the scope call — confirm scope and timeline.",
    "proposal_sent": "Nudge on the proposal — offer to walk them through it.",
    "signed_proposal": "Signed — chase kickoff date and first payment.",
}

_DEFAULT_SUGGESTION = "Gone quiet — follow up."


@dataclass(frozen=True)
class Nudge:
    app: Application
    title: str
    days_stale: int
    suggestion: str


def stale_applications(
    store: Store, days: int = 7, now: datetime | None = None,
) -> list[Nudge]:
    """Non-terminal applications untouched for `days`+ days, most stale first.

    An application is stale when the ball has been in someone's court longer
    than `days` — measured off `updated_at`, which every stage transition
    bumps. Terminal stages (won/rejected/dropped) are done, never stale.
    """
    now = now or datetime.now(UTC)
    cutoff = (now - timedelta(days=days)).isoformat()
    placeholders = ",".join("?" * len(TERMINAL))
    with store._conn() as c:  # noqa: SLF001 — same package
        rows = c.execute(
            f"SELECT a.job_key, a.stage, a.notes, a.channel, a.applied_at, "
            f"a.updated_at, j.title "
            f"FROM applications a JOIN jobs j ON j.key = a.job_key "
            f"WHERE a.stage NOT IN ({placeholders}) AND a.updated_at < ? "
            f"ORDER BY a.updated_at ASC",
            (*TERMINAL, cutoff),
        ).fetchall()

    nudges: list[Nudge] = []
    for row in rows:
        app = _row_to_app(row)
        days_stale = int((now - app.updated_at).total_seconds() // 86400)
        nudges.append(
            Nudge(
                app=app,
                title=row["title"],
                days_stale=days_stale,
                suggestion=SUGGESTION_BY_STAGE.get(app.stage, _DEFAULT_SUGGESTION),
            )
        )
    return nudges


__all__ = ["Nudge", "stale_applications", "SUGGESTION_BY_STAGE"]
