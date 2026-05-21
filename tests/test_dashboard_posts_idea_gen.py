"""AppTest coverage for the Posts page idea-driven generator."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return Store(f"sqlite:///{db_path}")


def _harness(tmp_path: Path) -> str:
    h = tmp_path / "harness.py"
    h.write_text(
        "from career_os.dashboard.pages.posts import render\nrender()\n"
    )
    return str(h)


def test_posts_page_renders_idea_generator_section(tmp_path, isolated_db):
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    caption_blob = " ".join(c.value for c in at.caption)
    assert "Paste an idea" in caption_blob or "references for the model" in caption_blob


def test_posts_page_idea_generator_dry_run_creates_drafts(
    tmp_path, isolated_db, monkeypatch,
):
    """Pre-populate idea fields, click Generate; expect new posts in DB."""
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception

    # Pre-populate the idea form fields.
    at.session_state["idea_gen_text"] = (
        "Streaming Claude in prod is harder than the demo. "
        "https://docs.anthropic.com/streaming"
    )
    at.session_state["idea_gen_urls"] = ""
    at.session_state["idea_gen_angle"] = "production-reality"
    at.session_state["idea_gen_audience"] = ""
    at.session_state["idea_gen_channels"] = ["x", "linkedin"]
    at.run(timeout=15)

    # Find and click the Generate button.
    gen_btn = next(
        (b for b in at.button if b.key == "idea_gen_submit"),
        None,
    )
    assert gen_btn is not None
    gen_btn.click().run(timeout=20)
    assert not at.exception

    drafts = posts_lib.list_posts(isolated_db)
    channels = {p.channel for p in drafts}
    assert {"x", "linkedin"}.issubset(channels)
    for d in drafts:
        assert d.body  # dry-run still produces a body
        assert "idea" in (d.notes or "").lower()
