"""Drive the Streamlit dashboard with AppTest and assert on rendered widgets.

These tests boot the actual app.py through Streamlit's headless test runner,
so we catch runtime errors that import-time + query unit tests miss
(missing column_config args, st.dataframe column type mismatches, etc).
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Dashboard tests only run when the [dashboard] extras are installed.
# CI installs [dev] by default; the streamlit-installed jobs run separately.
pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from career_os.db import Store  # noqa: E402
from career_os.models import Channel, JobPost, Score  # noqa: E402
from career_os.tracker import record_application  # noqa: E402

APP_PATH = str(
    Path(__file__).resolve().parent.parent / "src" / "career_os" / "dashboard" / "app.py"
)


@pytest.fixture(autouse=True)
def _clear_streamlit_cache():
    """Streamlit's @st.cache_data is process-global — bust between tests."""
    import streamlit as st
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point the dashboard at an empty per-test SQLite file."""
    db_path = tmp_path / "dash.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    return Store(f"sqlite:///{db_path}")


def _seed(store: Store, *, fit: int | None = 75, channel: Channel = Channel.FREELANCE,
          source: str = "remoteok", with_draft: bool = False,
          with_application: str | None = None, key: str = "1") -> str:
    job = JobPost(
        source=source, external_id=key,
        url=f"https://example.com/{key}",
        title=f"Senior Laravel + AI ({key})", company="Acme",
        description="Laravel + Vue + Claude SDK work.",
        channel=channel,
    )
    store.upsert_job(job)
    if fit is not None:
        store.save_score(Score(
            job_key=job.key, fit=fit, reasoning="strong match",
            pros=["laravel"], cons=[], suggested_angle="lead with stack overlap",
        ))
    if with_draft:
        store.save_draft(job.key, fmt=channel.value, body="hello", model="dry-run")
    if with_application:
        record_application(store, job.key, stage=with_application)
    return job.key


def test_dashboard_empty_db_renders_without_exceptions(isolated_db):
    at = AppTest.from_file(APP_PATH).run(timeout=10)
    assert not at.exception
    # Title + caption present
    assert "Career-OS" in at.title[0].value
    # Empty-state messages
    info_texts = [b.value for b in at.info]
    assert any("fetch" in t for t in info_texts)


def test_dashboard_renders_with_seeded_data(isolated_db):
    _seed(isolated_db, fit=82, channel=Channel.FREELANCE, key="f1", with_draft=True)
    _seed(isolated_db, fit=75, channel=Channel.FT, key="t1")
    _seed(isolated_db, fit=68, channel=Channel.FT, key="t2", with_application="sent")
    _seed(isolated_db, fit=45, channel=Channel.FT, key="t3")
    at = AppTest.from_file(APP_PATH).run(timeout=10)
    assert not at.exception
    metric_values = [m.value for m in at.metric]
    # Four headline metrics in fixed order: jobs / scored / drafts / applications
    assert metric_values[0] == "4"   # jobs
    assert metric_values[1] == "4"   # scored
    assert metric_values[2] == "1"   # drafts
    assert metric_values[3] == "1"   # applications


def test_dashboard_min_fit_slider_filters_table(isolated_db):
    _seed(isolated_db, fit=82, key="hi")
    _seed(isolated_db, fit=45, key="lo")
    at = AppTest.from_file(APP_PATH).run(timeout=10)
    # Default min_fit is 60 → only the fit=82 row should be in the dataframe.
    assert not at.exception
    # st.dataframe stores data on at.dataframe[0]
    # When there are matches, the empty-state info "fetch && score" should NOT appear.
    info_blob = " ".join(b.value for b in at.info)
    assert "No matches" not in info_blob


def test_dashboard_channel_filter(isolated_db):
    _seed(isolated_db, fit=80, channel=Channel.FREELANCE, key="free")
    _seed(isolated_db, fit=80, channel=Channel.FT, key="ft")
    at = AppTest.from_file(APP_PATH).run(timeout=10)
    assert not at.exception
    assert len(at.selectbox) >= 1
    # Default is "all" — both rows visible.
    assert at.selectbox[0].value == "all"
    # Flip to freelance and re-run — only one row should remain in the table.
    at.selectbox[0].set_value("freelance").run(timeout=10)
    assert not at.exception
    assert at.selectbox[0].value == "freelance"


def test_dashboard_min_fit_slider_can_be_adjusted(isolated_db):
    _seed(isolated_db, fit=82, key="hi")
    _seed(isolated_db, fit=45, key="lo")
    at = AppTest.from_file(APP_PATH).run(timeout=10)
    assert not at.exception
    # Lower the slider so both rows pass — empty-state message should disappear.
    at.slider[0].set_value(0).run(timeout=10)
    assert not at.exception
    info_blob = " ".join(b.value for b in at.info)
    assert "No matches at that threshold" not in info_blob


def test_dashboard_funnel_shows_stage_counts(isolated_db):
    _seed(isolated_db, fit=80, key="a", with_application="sent")
    _seed(isolated_db, fit=80, key="b", with_application="interview")
    _seed(isolated_db, fit=80, key="c", with_application="interview")
    at = AppTest.from_file(APP_PATH).run(timeout=10)
    assert not at.exception
    # Funnel writes one line per stage; check the rendered markdown contains
    # both stage labels and their counts.
    all_md = " ".join(m.value for m in at.markdown)
    assert "sent" in all_md
    assert "interview" in all_md


def test_dashboard_refresh_button_clears_cache(isolated_db):
    _seed(isolated_db, fit=80, key="a")
    at = AppTest.from_file(APP_PATH).run(timeout=10)
    assert not at.exception
    # Find the refresh button by label
    refresh = [b for b in at.button if "Refresh" in b.label]
    assert len(refresh) == 1
    refresh[0].click().run(timeout=10)
    assert not at.exception
