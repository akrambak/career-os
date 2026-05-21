"""AppTest coverage for the Mentions page."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from career_os import mentions as men_lib  # noqa: E402
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
        "from career_os.dashboard.pages.mentions import render\nrender()\n"
    )
    return str(h)


def test_mentions_page_renders_empty(tmp_path, isolated_db):
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    title_text = " ".join(t.value for t in at.title)
    assert "Mentions" in title_text


def test_mentions_page_renders_with_data(tmp_path, isolated_db):
    men_lib.upsert_mention(
        isolated_db, source="hn",
        source_url="https://news.ycombinator.com/item?id=1",
        matched_term="bak-dev.com",
        context_snippet="Check out bak-dev.com for the project",
        has_link_value=False,
    )
    men_lib.upsert_mention(
        isolated_db, source="devto",
        source_url="https://dev.to/x/post-1",
        matched_term="Career-OS",
        has_link_value=True,
    )
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    md_blob = " ".join(m.value for m in at.markdown)
    assert "bak-dev.com" in md_blob or "Career-OS" in md_blob


def test_mentions_status_metrics(tmp_path, isolated_db):
    m1 = men_lib.upsert_mention(
        isolated_db, source="hn",
        source_url="https://a/1", matched_term="bak-dev.com",
    )
    men_lib.upsert_mention(
        isolated_db, source="devto",
        source_url="https://b/2", matched_term="AkBak",
    )
    men_lib.set_status(isolated_db, m1.id, "converted")
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    assert len(at.metric) >= 4
    metric_values = [m.value for m in at.metric]
    assert "1" in metric_values
