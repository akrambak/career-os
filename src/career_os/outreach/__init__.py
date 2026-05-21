"""Outreach targets pipeline (SEO Feature 2).

State machine: researching → pitched → replied → accepted → published
                                     ↘            ↘
                                  declined       dropped

Per-category Claude pitches generated via `.generator.generate_pitch`.
Stale-pitch detection via `actions.gen_stale_outreach`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from ..db import Store

CATEGORIES = (
    "podcast", "guest_post", "directory", "haro",
    "roundup", "community", "newsletter", "unlinked_mention",
)

STAGES = (
    "researching", "pitched", "replied", "accepted",
    "published", "declined", "dropped",
)
TERMINAL = ("published", "declined", "dropped")
ACTIVE = tuple(s for s in STAGES if s not in TERMINAL)


@dataclass(frozen=True)
class OutreachTarget:
    id: int
    name: str
    site_url: str
    site_domain: str
    category: str
    contact: str | None
    pitch_angle: str | None
    stage: str
    value_score: int
    da_estimate: int | None
    target_backlink_url: str | None
    pitch_draft: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    pitched_at: datetime | None
    published_at: datetime | None


class StageTransitionError(ValueError):
    pass


# ---- CRUD ----------------------------------------------------------------

def _now() -> str:
    return datetime.now(UTC).isoformat()


def _domain_of(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except (ValueError, AttributeError):
        return ""


def add_target(
    store: Store, *,
    name: str, site_url: str, category: str,
    contact: str | None = None, pitch_angle: str | None = None,
    value_score: int = 5, da_estimate: int | None = None,
    target_backlink_url: str | None = None, notes: str | None = None,
) -> OutreachTarget:
    if not name.strip():
        raise ValueError("name is required")
    if not site_url.strip():
        raise ValueError("site_url is required")
    if category not in CATEGORIES:
        raise ValueError(
            f"category must be one of {CATEGORIES}, got {category!r}"
        )
    if not 1 <= value_score <= 10:
        raise ValueError("value_score must be in 1-10")
    site_domain = _domain_of(site_url)
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            """
            INSERT INTO outreach_targets (
                name, site_url, site_domain, category, contact,
                pitch_angle, stage, value_score, da_estimate,
                target_backlink_url, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'researching', ?, ?, ?, ?, ?, ?)
            """,
            (name.strip(), site_url.strip(), site_domain, category,
             contact, pitch_angle, value_score, da_estimate,
             target_backlink_url, notes, now, now),
        )
        target_id = c.execute(
            "SELECT last_insert_rowid() AS id"
        ).fetchone()["id"]
    return get_target(store, target_id)


def get_target(store: Store, target_id: int) -> OutreachTarget:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT * FROM outreach_targets WHERE id = ?", (target_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"outreach target {target_id} not found")
    return _row_to_target(row)


def list_targets(
    store: Store, *,
    stage: str | None = None,
    category: str | None = None,
    min_value: int = 0,
    limit: int = 100,
) -> list[OutreachTarget]:
    sql_parts = ["SELECT * FROM outreach_targets WHERE value_score >= ?"]
    params: list = [min_value]
    if stage:
        sql_parts.append("AND stage = ?")
        params.append(stage)
    if category:
        sql_parts.append("AND category = ?")
        params.append(category)
    sql_parts.append("ORDER BY value_score DESC, updated_at DESC LIMIT ?")
    params.append(limit)
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(" ".join(sql_parts), tuple(params)).fetchall()
    return [_row_to_target(r) for r in rows]


def update_target(
    store: Store, target_id: int, *,
    name: str | None = None, contact: str | None = None,
    pitch_angle: str | None = None, value_score: int | None = None,
    da_estimate: int | None = None,
    target_backlink_url: str | None = None,
    pitch_draft: str | None = None, notes: str | None = None,
) -> OutreachTarget:
    fields: list[str] = []
    params: list = []
    if name is not None:
        if not name.strip():
            raise ValueError("name cannot be blank")
        fields.append("name=?")
        params.append(name.strip())
    if contact is not None:
        fields.append("contact=?")
        params.append(contact)
    if pitch_angle is not None:
        fields.append("pitch_angle=?")
        params.append(pitch_angle)
    if value_score is not None:
        if not 1 <= value_score <= 10:
            raise ValueError("value_score must be 1-10")
        fields.append("value_score=?")
        params.append(int(value_score))
    if da_estimate is not None:
        fields.append("da_estimate=?")
        params.append(int(da_estimate))
    if target_backlink_url is not None:
        fields.append("target_backlink_url=?")
        params.append(target_backlink_url)
    if pitch_draft is not None:
        fields.append("pitch_draft=?")
        params.append(pitch_draft)
    if notes is not None:
        fields.append("notes=?")
        params.append(notes)
    if not fields:
        return get_target(store, target_id)
    fields.append("updated_at=?")
    params.append(_now())
    params.append(target_id)
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            f"UPDATE outreach_targets SET {', '.join(fields)} WHERE id=?",
            tuple(params),
        )
    return get_target(store, target_id)


def advance_stage(
    store: Store, target_id: int, *,
    to: str | None = None, notes: str | None = None,
) -> OutreachTarget:
    """Move along the stage machine. `to=None` advances one step."""
    target = get_target(store, target_id)
    if target.stage in TERMINAL:
        raise StageTransitionError(
            f"Target is terminal ({target.stage!r}) — cannot advance."
        )
    if to is None:
        # Default: research → pitched → replied → accepted → published
        # When stage is "replied" the default forward is "accepted".
        try:
            i = ACTIVE.index(target.stage)
        except ValueError:
            i = -1
        to = ACTIVE[i + 1] if i + 1 < len(ACTIVE) else "published"
    if to not in STAGES:
        raise StageTransitionError(
            f"Unknown stage {to!r}. Known: {STAGES}"
        )
    now = _now()
    extra_setters = ""
    extra_params: list = []
    if to == "pitched":
        extra_setters = ", pitched_at=COALESCE(pitched_at, ?)"
        extra_params.append(now)
    elif to == "published":
        extra_setters = ", published_at=COALESCE(published_at, ?)"
        extra_params.append(now)
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            f"UPDATE outreach_targets SET stage=?, updated_at=?, "
            f"notes=COALESCE(?, notes){extra_setters} WHERE id=?",
            (to, now, notes, *extra_params, target_id),
        )
    return get_target(store, target_id)


def delete_target(store: Store, target_id: int) -> bool:
    with store._conn() as c:  # noqa: SLF001
        cur = c.execute(
            "DELETE FROM outreach_targets WHERE id = ?", (target_id,),
        )
        return cur.rowcount > 0


# ---- aggregates ----------------------------------------------------------

def funnel_counts(store: Store) -> dict[str, dict[str, int]]:
    """Nested per-category funnel — every category seeded with all stages
    so callers can iterate without .get() defensiveness."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT category, stage, COUNT(*) AS n FROM outreach_targets "
            "GROUP BY category, stage",
        ).fetchall()
    counts: dict[str, dict[str, int]] = {
        cat: dict.fromkeys(STAGES, 0) for cat in CATEGORIES
    }
    for r in rows:
        cat = r["category"]
        if cat not in counts:
            counts[cat] = dict.fromkeys(STAGES, 0)
        counts[cat][r["stage"]] = int(r["n"])
    return counts


def counts_by_stage(store: Store) -> dict[str, int]:
    """Flat per-stage totals (across all categories)."""
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT stage, COUNT(*) AS n FROM outreach_targets GROUP BY stage",
        ).fetchall()
    counts = dict.fromkeys(STAGES, 0)
    for r in rows:
        counts[r["stage"]] = int(r["n"])
    return counts


def _row_to_target(row) -> OutreachTarget:
    return OutreachTarget(
        id=int(row["id"]),
        name=row["name"],
        site_url=row["site_url"],
        site_domain=row["site_domain"] or "",
        category=row["category"],
        contact=row["contact"],
        pitch_angle=row["pitch_angle"],
        stage=row["stage"],
        value_score=int(row["value_score"]),
        da_estimate=(int(row["da_estimate"])
                     if row["da_estimate"] is not None else None),
        target_backlink_url=row["target_backlink_url"],
        pitch_draft=row["pitch_draft"],
        notes=row["notes"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        pitched_at=(datetime.fromisoformat(row["pitched_at"])
                    if row["pitched_at"] else None),
        published_at=(datetime.fromisoformat(row["published_at"])
                      if row["published_at"] else None),
    )


__all__ = [
    "CATEGORIES", "STAGES", "TERMINAL", "ACTIVE",
    "OutreachTarget", "StageTransitionError",
    "add_target", "get_target", "list_targets",
    "update_target", "advance_stage", "delete_target",
    "funnel_counts", "counts_by_stage",
]
