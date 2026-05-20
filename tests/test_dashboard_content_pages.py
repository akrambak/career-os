"""AppTest coverage for the Ideas + Posts pages."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from career_os.dashboard import ideas as ideas_lib  # noqa: E402
from career_os.dashboard import posts as posts_lib  # noqa: E402
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


def _harness(tmp_path: Path, page_module: str) -> str:
    h = tmp_path / "harness.py"
    h.write_text(
        f"from career_os.dashboard.pages.{page_module} import render\nrender()\n"
    )
    return str(h)


# ---- Ideas page ----------------------------------------------------------

def test_ideas_page_renders_empty(tmp_path, isolated_db):
    at = AppTest.from_file(_harness(tmp_path, "ideas")).run(timeout=15)
    assert not at.exception
    title = " ".join(t.value for t in at.title)
    assert "Ideas" in title
    info_blob = " ".join(b.value for b in at.info)
    assert "No ideas yet" in info_blob


def test_ideas_page_renders_with_seeded(tmp_path, isolated_db):
    ideas_lib.add_idea(
        isolated_db, title="Build Career-OS in public",
        hook="One project, three outcomes", channel="blog", tags=["claude"],
    )
    ideas_lib.add_idea(isolated_db, title="HN launch thread", channel="hn")
    at = AppTest.from_file(_harness(tmp_path, "ideas")).run(timeout=15)
    assert not at.exception
    md_blob = " ".join(m.value for m in at.markdown)
    assert "Build Career-OS in public" in md_blob
    assert "HN launch thread" in md_blob


def test_ideas_channel_metrics_render(tmp_path, isolated_db):
    ideas_lib.add_idea(isolated_db, title="A", channel="blog")
    ideas_lib.add_idea(isolated_db, title="B", channel="blog")
    ideas_lib.add_idea(isolated_db, title="C", channel="linkedin")
    at = AppTest.from_file(_harness(tmp_path, "ideas")).run(timeout=15)
    assert not at.exception
    # The page renders a Streamlit metric per CHANNELS — at least 6 tiles.
    assert len(at.metric) >= 6


# ---- Posts page ----------------------------------------------------------

def test_posts_page_renders_empty(tmp_path, isolated_db):
    at = AppTest.from_file(_harness(tmp_path, "posts")).run(timeout=15)
    assert not at.exception
    title = " ".join(t.value for t in at.title)
    assert "Posts" in title
    info_blob = " ".join(b.value for b in at.info)
    assert "No posts yet" in info_blob


def test_posts_page_renders_with_seeded(tmp_path, isolated_db):
    posts_lib.add_post(
        isolated_db, title="First milestone", channel="blog",
        body="# Hi\n\nFirst body.\n",
    )
    posts_lib.add_post(isolated_db, title="LinkedIn launch", channel="linkedin")
    at = AppTest.from_file(_harness(tmp_path, "posts")).run(timeout=15)
    assert not at.exception
    md_blob = " ".join(m.value for m in at.markdown)
    assert "First milestone" in md_blob
    assert "LinkedIn launch" in md_blob


def test_posts_status_metrics(tmp_path, isolated_db):
    a = posts_lib.add_post(isolated_db, title="A")
    b = posts_lib.add_post(isolated_db, title="B")
    posts_lib.set_status(isolated_db, a.id, "ready")
    posts_lib.set_status(isolated_db, b.id, "posted")
    at = AppTest.from_file(_harness(tmp_path, "posts")).run(timeout=15)
    assert not at.exception
    metric_values = [m.value for m in at.metric]
    # Drafting, Ready, Posted in that order at the top of the page
    assert metric_values[0] == "0"
    assert metric_values[1] == "1"
    assert metric_values[2] == "1"
