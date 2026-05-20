"""AppTest coverage for the Trends page."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from career_os.db import Store  # noqa: E402
from career_os.trends import upsert_trend  # noqa: E402


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
        "from career_os.dashboard.pages.trends import render\nrender()\n"
    )
    return str(h)


def test_trends_page_renders_empty(tmp_path, isolated_db):
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    title_text = " ".join(t.value for t in at.title)
    assert "Trends" in title_text
    info_blob = " ".join(b.value for b in at.info)
    assert "Nothing above" in info_blob or "Scan now" in info_blob


def test_trends_page_renders_with_data(tmp_path, isolated_db):
    upsert_trend(
        isolated_db, source="hn", external_id="1",
        url="https://news.ycombinator.com/item?id=1",
        title="Anthropic releases tool streaming API",
        score=420, comment_count=187,
    )
    upsert_trend(
        isolated_db, source="devto", external_id="2",
        url="https://dev.to/a/2",
        title="Building agents with Claude SDK",
        score=250, comment_count=18, tags=["claude", "ai"],
    )
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    md_blob = " ".join(m.value for m in at.markdown)
    assert "Anthropic" in md_blob or "tool streaming" in md_blob
    assert "Claude SDK" in md_blob or "agents" in md_blob


def test_trends_page_source_metrics(tmp_path, isolated_db):
    upsert_trend(isolated_db, source="hn", external_id="1",
                url="https://a", title="A", score=10)
    upsert_trend(isolated_db, source="hn", external_id="2",
                url="https://b", title="B", score=20, comment_count=5)
    upsert_trend(isolated_db, source="devto", external_id="3",
                url="https://c", title="C", score=5)
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    # 4 source metrics: hn / devto / tavily / total.
    assert len(at.metric) >= 4
    metric_values = [m.value for m in at.metric]
    assert "3" in metric_values  # total
