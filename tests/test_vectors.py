from __future__ import annotations

from career_os.db import Store
from career_os.db.vectors import HashEmbedder
from career_os.trends import (
    collapse_duplicate_trends,
    embed_missing_trends,
    find_similar_trends,
    list_trends,
    upsert_trend,
)


def _store(tmp_path) -> Store:
    return Store(f"sqlite:///{tmp_path / 'db.sqlite'}")


def test_embed_and_similar_ranks_lexical_match_first(tmp_path):
    store = _store(tmp_path)
    emb = HashEmbedder()
    upsert_trend(
        store, source="hn", external_id="1",
        url="https://a", title="Postgres pgvector tutorial for semantic search",
    )
    upsert_trend(
        store, source="hn", external_id="2",
        url="https://b", title="Rust async runtime benchmarks for 2026",
    )
    assert embed_missing_trends(store, emb) == 2
    # Re-running is idempotent — nothing new to embed.
    assert embed_missing_trends(store, emb) == 0

    hits = find_similar_trends(
        store, emb, "pgvector semantic search in Postgres", k=2
    )
    assert len(hits) == 2
    top, dist = hits[0]
    assert "pgvector" in top.title
    # Nearest is strictly closer than the unrelated trend.
    assert dist < hits[1][1]


def test_find_similar_respects_max_distance(tmp_path):
    store = _store(tmp_path)
    emb = HashEmbedder()
    upsert_trend(
        store, source="hn", external_id="1",
        url="https://a", title="Rust async runtime benchmarks for 2026",
    )
    embed_missing_trends(store, emb)
    # A totally unrelated query past the cutoff returns nothing.
    assert find_similar_trends(
        store, emb, "knitting patterns for winter scarves", max_distance=0.05
    ) == []


def test_collapse_duplicate_trends_dry_run_then_apply(tmp_path):
    store = _store(tmp_path)
    emb = HashEmbedder()
    # Two near-identical trends from different sources (exact dedup can't see
    # them) + one distinct. The high-signal one should win.
    upsert_trend(
        store, source="hn", external_id="1", score=500,
        url="https://a", title="Postgres pgvector tutorial for semantic search",
    )
    upsert_trend(
        store, source="devto", external_id="2", score=2,
        url="https://b", title="Postgres pgvector tutorial for semantic search",
    )
    upsert_trend(
        store, source="hn", external_id="3", score=300,
        url="https://c", title="Rust async runtime benchmarks for 2026",
    )

    pairs = collapse_duplicate_trends(store, emb, max_distance=0.1, apply=False)
    assert len(pairs) == 1
    keep_id, drop_id, _ = pairs[0]
    # Dry-run changes nothing.
    assert len(list_trends(store, hide_used=False, limit=50)) == 3

    applied = collapse_duplicate_trends(store, emb, max_distance=0.1, apply=True)
    assert len(applied) == 1
    remaining = {t.id for t in list_trends(store, hide_used=False, limit=50)}
    assert len(remaining) == 2
    assert drop_id not in remaining
    assert keep_id in remaining


def test_vectors_noop_without_embedder_is_not_triggered(tmp_path):
    # default_embedder returns None without a Voyage key — callers must guard.
    from career_os.db.vectors import default_embedder
    assert default_embedder(None) is None
