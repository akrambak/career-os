"""Mention Hunter (SEO Feature 3) — auto-discover references to the
user's domain / repo / handles across HN, dev.to, GitHub.

Each mention is classified `has_link=True/False` based on substring
detection against the user's URLs. Unlinked mentions become Inbox
actions: the user converts each into a real backlink (via the
backlinks table) or a directed outreach pitch (via outreach_targets).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..db import Store

SOURCES = ("hn", "devto", "github", "reddit", "tavily", "manual")
STATUSES = ("open", "converted", "dismissed", "linked")


@dataclass(frozen=True)
class Mention:
    id: int
    source: str
    source_url: str
    matched_term: str
    context_snippet: str | None
    has_link: bool
    status: str
    discovered_at: datetime
    notes: str | None


# Terms we look for — the user's brand surface. Static for now; lift to
# Profile fields if it ever needs to be per-user configurable.
DEFAULT_TERMS: tuple[str, ...] = (
    "bak-dev.com",
    "akrambak/career-os",
    "github.com/akrambak/career-os",
    "AkBak",
    "Bakhouche Akram",
)

# URL fragments that, if present in the source body, indicate a real link
# back to us (vs. just a brand-name mention).
LINK_PRESENCE_FRAGMENTS: tuple[str, ...] = (
    "bak-dev.com",
    "akrambak/career-os",
    "github.com/akrambak",
)


# ---- CRUD ----------------------------------------------------------------

def _now() -> str:
    return datetime.now(UTC).isoformat()


def has_link(body: str | None) -> bool:
    """True if the body contains any of our URL fragments. Substring
    match — good enough for the discovery pass; not a guarantee that the
    rendered HTML has a real <a href> (false positives are OK because the
    user reviews each row)."""
    if not body:
        return False
    haystack = body.lower()
    return any(frag.lower() in haystack for frag in LINK_PRESENCE_FRAGMENTS)


def upsert_mention(
    store: Store, *,
    source: str, source_url: str, matched_term: str,
    context_snippet: str | None = None,
    has_link_value: bool = False,
    notes: str | None = None,
) -> Mention:
    """Idempotent on (source_url, matched_term). Re-discovery refreshes
    has_link / snippet but never re-opens a manually-resolved mention."""
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}")
    now = _now()
    with store._conn() as c:  # noqa: SLF001
        existing = c.execute(
            "SELECT id, status FROM mentions "
            "WHERE source_url = ? AND matched_term = ?",
            (source_url, matched_term),
        ).fetchone()
        if existing:
            mention_id = existing["id"]
            # Only refresh fields for OPEN mentions — once dismissed /
            # converted / linked the user has made a decision we respect.
            if existing["status"] == "open":
                c.execute(
                    "UPDATE mentions SET context_snippet=?, has_link=? "
                    "WHERE id=?",
                    (context_snippet, 1 if has_link_value else 0, mention_id),
                )
        else:
            c.execute(
                """
                INSERT INTO mentions (
                    source, source_url, matched_term, context_snippet,
                    has_link, status, discovered_at, notes
                ) VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
                """,
                (source, source_url, matched_term, context_snippet,
                 1 if has_link_value else 0, now, notes),
            )
            mention_id = c.execute(
                "SELECT last_insert_rowid() AS id"
            ).fetchone()["id"]
    return get_mention(store, mention_id)


def get_mention(store: Store, mention_id: int) -> Mention:
    with store._conn() as c:  # noqa: SLF001
        row = c.execute(
            "SELECT * FROM mentions WHERE id = ?", (mention_id,),
        ).fetchone()
    if row is None:
        raise LookupError(f"mention {mention_id} not found")
    return _row_to_mention(row)


def list_mentions(
    store: Store, *,
    status: str | None = "open",
    source: str | None = None,
    has_link_value: bool | None = None,
    limit: int = 100,
) -> list[Mention]:
    sql_parts = ["SELECT * FROM mentions WHERE 1=1"]
    params: list = []
    if status:
        sql_parts.append("AND status = ?")
        params.append(status)
    if source:
        sql_parts.append("AND source = ?")
        params.append(source)
    if has_link_value is not None:
        sql_parts.append("AND has_link = ?")
        params.append(1 if has_link_value else 0)
    sql_parts.append("ORDER BY discovered_at DESC LIMIT ?")
    params.append(limit)
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(" ".join(sql_parts), tuple(params)).fetchall()
    return [_row_to_mention(r) for r in rows]


def set_status(store: Store, mention_id: int, status: str) -> Mention:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    with store._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE mentions SET status=? WHERE id=?",
            (status, mention_id),
        )
    return get_mention(store, mention_id)


def delete_mention(store: Store, mention_id: int) -> bool:
    with store._conn() as c:  # noqa: SLF001
        cur = c.execute("DELETE FROM mentions WHERE id = ?", (mention_id,))
        return cur.rowcount > 0


def counts_by_status(store: Store) -> dict[str, int]:
    with store._conn() as c:  # noqa: SLF001
        rows = c.execute(
            "SELECT status, COUNT(*) AS n FROM mentions GROUP BY status",
        ).fetchall()
    counts = dict.fromkeys(STATUSES, 0)
    for r in rows:
        counts[r["status"]] = int(r["n"])
    return counts


# ---- cross-feature converters --------------------------------------------

def convert_to_backlink(
    store: Store, mention_id: int, *,
    target_url: str, anchor_text: str | None = None, rel: str = "dofollow",
    da_estimate: int | None = None,
) -> int:
    """Promote an unlinked mention to a real backlinks row (status='live'
    by assumption — the user has just gone and gotten the link added).
    Returns the new backlink id. The mention is flipped to 'converted'.

    Caller should pass the FINAL target URL they negotiated with the
    publisher (often bak-dev.com/blog/<slug> or github.com/akrambak/
    career-os).
    """
    from ..backlinks import upsert_backlink
    mention = get_mention(store, mention_id)
    backlink = upsert_backlink(
        store,
        source_url=mention.source_url,
        target_url=target_url,
        anchor_text=anchor_text,
        rel=rel,
        status="live",
        da_estimate=da_estimate,
        discovered_via="mention_hunter",
        notes=f"Converted from mention #{mention.id} ({mention.source})",
    )
    set_status(store, mention_id, "converted")
    return backlink.id


def to_outreach_target(
    store: Store, mention_id: int, *,
    name: str | None = None, pitch_angle: str | None = None,
    value_score: int = 5, target_backlink_url: str | None = None,
) -> int:
    """Spawn an outreach_targets row from a mention so the user can pitch
    converting the mention to a link. Returns the outreach target id."""
    from ..outreach import add_target
    mention = get_mention(store, mention_id)
    target = add_target(
        store,
        name=name or f"Convert mention: {mention.source_url[:60]}",
        site_url=mention.source_url,
        category="unlinked_mention",
        pitch_angle=pitch_angle or mention.context_snippet,
        value_score=value_score,
        target_backlink_url=target_backlink_url,
        notes=f"From mention #{mention.id} ({mention.source})",
    )
    return target.id


# ---- internals ----------------------------------------------------------

def _row_to_mention(row) -> Mention:
    return Mention(
        id=int(row["id"]),
        source=row["source"],
        source_url=row["source_url"],
        matched_term=row["matched_term"],
        context_snippet=row["context_snippet"],
        has_link=bool(row["has_link"]),
        status=row["status"],
        discovered_at=datetime.fromisoformat(row["discovered_at"]),
        notes=row["notes"],
    )


__all__ = [
    "SOURCES", "STATUSES", "DEFAULT_TERMS", "LINK_PRESENCE_FRAGMENTS",
    "Mention",
    "has_link",
    "upsert_mention", "get_mention", "list_mentions",
    "set_status", "delete_mention", "counts_by_status",
    "convert_to_backlink", "to_outreach_target",
]
