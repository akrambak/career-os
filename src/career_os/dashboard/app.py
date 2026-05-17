"""Streamlit dashboard entry point. Launch with: `career-os dashboard`.

This module wires together the registered pages via `st.navigation`. Pages
live under `pages/`. To add one:

    1. Drop a new file under `src/career_os/dashboard/pages/<name>.py`
       exposing a `render()` callable (see pages/__init__.py for the recipe).
    2. Import it below and append a `st.Page(...)` entry to `PAGES`.
    3. Optionally add a unit test under tests/.

Imports are absolute (`career_os.*`) so this file works whether streamlit
invokes it as a script or our CLI runs it via `python -m streamlit run`.
"""
from __future__ import annotations

import streamlit as st

from career_os.dashboard.pages import kpis, overview, todos

st.set_page_config(
    page_title="Career-OS",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = [
    st.Page(overview.render, title="Overview", icon="📊",
            url_path="overview", default=True),
    st.Page(todos.render, title="To-Do · Plan", icon="✅",
            url_path="todos"),
    st.Page(kpis.render, title="KPIs", icon="📈",
            url_path="kpis"),
]


def main() -> None:
    pg = st.navigation(PAGES, position="sidebar", expanded=True)
    pg.run()


main()
