"""AppTest coverage for the Backlinks page."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from career_os import backlinks as bl_lib  # noqa: E402
from career_os.db import Store  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_streamlit_cache():
    import streamlit as st
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "dash.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    return Store(f"sqlite:///{db_path}")


def _harness(tmp_path: Path) -> str:
    h = tmp_path / "harness.py"
    h.write_text(
        "from career_os.dashboard.pages.backlinks import render\nrender()\n"
    )
    return str(h)


def test_backlinks_page_renders_empty(tmp_path, isolated_db):
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    title_text = " ".join(t.value for t in at.title)
    assert "Backlinks" in title_text


def test_backlinks_page_renders_with_data(tmp_path, isolated_db):
    bl_lib.upsert_backlink(
        isolated_db,
        source_url="https://news.ycombinator.com/item?id=123",
        target_url="https://bak-dev.com/blog/career-os",
        anchor_text="Career-OS", rel="dofollow",
    )
    bl_lib.upsert_backlink(
        isolated_db,
        source_url="https://dev.to/akbak/post-1",
        target_url="https://bak-dev.com/blog/x",
        rel="nofollow",
    )
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    md_blob = " ".join(m.value for m in at.markdown)
    assert "news.ycombinator.com" in md_blob or "dev.to" in md_blob


def test_backlinks_status_metrics(tmp_path, isolated_db):
    bl_lib.upsert_backlink(
        isolated_db, source_url="https://a/1",
        target_url="https://t", status="live", rel="dofollow",
    )
    bl_lib.upsert_backlink(
        isolated_db, source_url="https://b/1",
        target_url="https://t", status="dead",
    )
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    metric_values = [m.value for m in at.metric]
    # 4 metrics: live / dead+removed / dofollow% / referring domains.
    assert len(at.metric) >= 4
    assert "1" in metric_values  # live count == 1
