"""AppTest coverage for the Outreach page."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from career_os import outreach as out_lib  # noqa: E402
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
        "from career_os.dashboard.pages.outreach import render\nrender()\n"
    )
    return str(h)


def test_outreach_page_renders_empty(tmp_path, isolated_db):
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    title_text = " ".join(t.value for t in at.title)
    assert "Outreach" in title_text


def test_outreach_page_renders_with_data(tmp_path, isolated_db):
    out_lib.add_target(
        isolated_db, name="Smashing guest post",
        site_url="https://smashingmagazine.com", category="guest_post",
    )
    out_lib.add_target(
        isolated_db, name="syntax.fm podcast",
        site_url="https://syntax.fm", category="podcast",
    )
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    md_blob = " ".join(m.value for m in at.markdown)
    assert "Smashing" in md_blob
    assert "syntax.fm" in md_blob


def test_outreach_stage_metrics(tmp_path, isolated_db):
    a = out_lib.add_target(
        isolated_db, name="A", site_url="https://a/", category="podcast",
    )
    out_lib.add_target(
        isolated_db, name="B", site_url="https://b/", category="podcast",
    )
    out_lib.advance_stage(isolated_db, a.id, to="published")
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    # 4 stage metrics on the header.
    assert len(at.metric) >= 4
    metric_values = [m.value for m in at.metric]
    # One published, one researching.
    assert "1" in metric_values
