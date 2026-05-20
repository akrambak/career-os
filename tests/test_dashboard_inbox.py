"""AppTest coverage for the Inbox page."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from career_os import actions as actions_lib  # noqa: E402
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
        "from career_os.dashboard.pages.inbox import render\nrender()\n"
    )
    return str(h)


def test_inbox_page_renders_empty(tmp_path, isolated_db):
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    title_text = " ".join(t.value for t in at.title)
    assert "Inbox" in title_text
    info_blob = " ".join(b.value for b in at.info)
    assert "Inbox zero" in info_blob


def test_inbox_page_renders_actions(tmp_path, isolated_db):
    actions_lib.upsert_action(
        isolated_db, kind="review_job", title="Senior Laravel @ Acme",
        severity="urgent", target_kind="job", target_id="test:1",
    )
    actions_lib.upsert_action(
        isolated_db, kind="send_draft", title="Send draft @ Beta",
        severity="normal", target_kind="job", target_id="test:2",
    )
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    md_blob = " ".join(m.value for m in at.markdown)
    assert "Senior Laravel @ Acme" in md_blob
    assert "Send draft @ Beta" in md_blob


def test_inbox_metrics_render(tmp_path, isolated_db):
    actions_lib.upsert_action(
        isolated_db, kind="x", title="a", severity="urgent",
        target_kind="t", target_id="1",
    )
    actions_lib.upsert_action(
        isolated_db, kind="x", title="b", severity="normal",
        target_kind="t", target_id="2",
    )
    at = AppTest.from_file(_harness(tmp_path)).run(timeout=15)
    assert not at.exception
    values = [m.value for m in at.metric]
    # 4 metrics: urgent / normal / low / total
    assert "1" in values  # urgent or normal == 1
    assert "2" in values  # total == 2
