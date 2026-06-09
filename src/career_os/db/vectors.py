"""Vector search via the sqlite-vec extension — kept optional so the
relational app never depends on it. If the wheel is missing or the platform
can't load extensions, `load_vec` returns False and every caller degrades to
a no-op (exact-match behavior, unchanged).

Embeddings come from a pluggable `Embedder`:
- `VoyageEmbedder` — production. Voyage AI is Anthropic's recommended
  embeddings partner (Anthropic ships no embeddings endpoint of its own).
- `HashEmbedder` — deterministic, dependency-free, offline. Captures lexical
  overlap only (not semantics), but enough to exercise the plumbing in tests
  without a network round-trip.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import sqlite3
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

VEC_TRENDS = "vec_trends"

_VEC_IMPORTABLE: bool | None = None


def vec_supported() -> bool:
    """Whether the `sqlite_vec` wheel is importable. Cached after first check."""
    global _VEC_IMPORTABLE
    if _VEC_IMPORTABLE is None:
        try:
            import sqlite_vec  # noqa: F401

            _VEC_IMPORTABLE = True
        except ModuleNotFoundError:
            _VEC_IMPORTABLE = False
    return _VEC_IMPORTABLE


def load_vec(conn: sqlite3.Connection) -> bool:
    """Load sqlite-vec into `conn` (extensions are per-connection). Returns
    True on success; False if unavailable — callers treat False as 'skip'."""
    if not vec_supported():
        return False
    import sqlite_vec

    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except (sqlite3.OperationalError, AttributeError) as exc:
        logger.warning("sqlite-vec load failed: %s", exc)
        return False


def ensure_vec_table(conn: sqlite3.Connection, table: str, dims: int) -> None:
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
        f"row_id integer primary key, "
        f"embedding float[{dims}] distance_metric=cosine)"
    )


def upsert_embedding(
    conn: sqlite3.Connection, table: str, row_id: int, vector: list[float]
) -> None:
    import sqlite_vec

    blob = sqlite_vec.serialize_float32(vector)
    conn.execute(f"DELETE FROM {table} WHERE row_id = ?", (row_id,))
    conn.execute(
        f"INSERT INTO {table}(row_id, embedding) VALUES (?, ?)", (row_id, blob)
    )


def search(
    conn: sqlite3.Connection, table: str, vector: list[float], k: int
) -> list[tuple[int, float]]:
    """KNN over `table`. Returns [(row_id, cosine_distance)] nearest-first."""
    import sqlite_vec

    blob = sqlite_vec.serialize_float32(vector)
    rows = conn.execute(
        f"SELECT row_id, distance FROM {table} "
        f"WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
        (blob, k),
    ).fetchall()
    return [(int(r["row_id"]), float(r["distance"])) for r in rows]


def existing_ids(conn: sqlite3.Connection, table: str) -> set[int]:
    try:
        rows = conn.execute(f"SELECT row_id FROM {table}").fetchall()
    except sqlite3.OperationalError:
        return set()
    return {int(r[0]) for r in rows}


# ---- embedders -----------------------------------------------------------


@runtime_checkable
class Embedder(Protocol):
    dims: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


_TOKEN_RE = re.compile(r"[^a-z0-9]+")


class HashEmbedder:
    # 1024 buckets keeps hash collisions rare enough that lexical overlap —
    # not accidental bucket clashes — drives cosine distance.
    def __init__(self, dims: int = 1024) -> None:
        self.dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for tok in _TOKEN_RE.split(text.lower()):
            if len(tok) <= 2:
                continue
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)  # noqa: S324
            vec[h % self.dims] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]


class VoyageEmbedder:
    def __init__(
        self, api_key: str, model: str = "voyage-3", dims: int = 1024
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.dims = dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        r = httpx.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts, "input_type": "document"},
            timeout=30.0,
        )
        r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]


def default_embedder(voyage_api_key: str | None) -> Embedder | None:
    """Production embedder, or None when vectors can't run (no wheel / no key).
    Deliberately does NOT fall back to HashEmbedder — lexical-only vectors in
    production would flag false duplicates."""
    if not vec_supported() or not voyage_api_key:
        return None
    return VoyageEmbedder(voyage_api_key)
