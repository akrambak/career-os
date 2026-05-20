"""Unit tests for the watermark module + Store helpers (Tier 2, Upgrade 6)."""
from __future__ import annotations

import pytest

from career_os.db import Store
from career_os.watermark import Watermark, WatermarkCtx


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'wm.db'}")


# ---- Store roundtrip -----------------------------------------------------

def test_get_watermark_returns_none_when_missing(store):
    assert store.get_watermark("nope") is None


def test_save_then_get_roundtrip(store):
    store.save_watermark(
        source="remoteok", last_fetched_at="2026-05-19T12:00:00+00:00",
        last_status="ok", last_external_id="abc",
    )
    wm = store.get_watermark("remoteok")
    assert wm is not None
    assert wm.source == "remoteok"
    assert wm.last_status == "ok"
    assert wm.last_external_id == "abc"


def test_save_upsert_preserves_unspecified_fields(store):
    """COALESCE in the upsert means a second write with only one field
    set doesn't blank out the others."""
    store.save_watermark(
        source="wwr", last_fetched_at="2026-05-19T12:00:00+00:00",
        last_status="ok", etag="W/\"abc\"", last_modified="Mon, 19 May 2026 12:00:00 GMT",
    )
    # Second write — only status changes. ETag must remain.
    store.save_watermark(
        source="wwr", last_fetched_at="2026-05-19T13:00:00+00:00",
        last_status="unchanged",
    )
    wm = store.get_watermark("wwr")
    assert wm.last_status == "unchanged"
    assert wm.etag == 'W/"abc"'
    assert wm.last_modified == "Mon, 19 May 2026 12:00:00 GMT"


def test_list_watermarks_returns_all(store):
    store.save_watermark(
        source="a", last_fetched_at="2026-05-19T12:00:00+00:00", last_status="ok",
    )
    store.save_watermark(
        source="b", last_fetched_at="2026-05-19T13:00:00+00:00", last_status="failed",
    )
    rows = store.list_watermarks()
    assert {w.source for w in rows} == {"a", "b"}


# ---- WatermarkCtx --------------------------------------------------------

def test_ctx_get_returns_what_getter_returns():
    def getter(key):
        return Watermark(
            source=key,
            last_fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            last_status="ok",
        )
    ctx = WatermarkCtx(getter=getter)
    wm = ctx.get("anything")
    assert wm is not None and wm.source == "anything"


def test_ctx_record_stages_fields():
    ctx = WatermarkCtx(getter=lambda k: None)
    ctx.record("remoteok", status="ok", last_external_id="123")
    assert ctx.records == {"remoteok": {"last_status": "ok", "last_external_id": "123"}}


def test_ctx_record_merges_repeated_calls():
    ctx = WatermarkCtx(getter=lambda k: None)
    ctx.record("remoteok", status="ok")
    ctx.record("remoteok", last_external_id="42")
    assert ctx.records["remoteok"] == {"last_status": "ok", "last_external_id": "42"}


def test_ctx_flush_calls_save_with_records(store):
    ctx = WatermarkCtx(getter=lambda k: None)
    ctx.record("a", status="ok", etag='W/"abc"')
    ctx.record("b", status="unchanged")
    ctx.flush(store.save_watermark)
    a = store.get_watermark("a")
    b = store.get_watermark("b")
    assert a.last_status == "ok"
    assert a.etag == 'W/"abc"'
    assert b.last_status == "unchanged"


def test_ctx_flush_defaults_status_to_ok_when_omitted(store):
    ctx = WatermarkCtx(getter=lambda k: None)
    # Scraper recorded an id but forgot status.
    ctx.record("a", last_external_id="42")
    ctx.flush(store.save_watermark)
    wm = store.get_watermark("a")
    assert wm.last_status == "ok"
    assert wm.last_external_id == "42"
