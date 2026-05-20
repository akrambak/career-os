---
name: add-dashboard-page
description: Add a new page to the Career-OS Streamlit dashboard. Use when the user says "add a page for X", "new dashboard tab", or wants a UI surface on top of stored data. Walks the page module + navigation wiring + queries-layer + AppTest fixture recipe.
---

# Add a new dashboard page

The dashboard is a Streamlit multi-page app wired via `st.navigation`. Each
page is one module under `src/career_os/dashboard/pages/` exposing a
`render()` callable. Navigation entries live in `src/career_os/dashboard/app.py`.

## Files you will touch

| Path | Why |
|---|---|
| `src/career_os/dashboard/pages/<name>.py` | the page itself (UI only) |
| `src/career_os/dashboard/<name>.py` (or extend `queries.py`) | data layer — UI-free, testable without streamlit |
| `src/career_os/dashboard/app.py` | add `st.Page(...)` to the `PAGES` list |
| `tests/test_dashboard_<name>.py` | AppTest harness test |

If the page needs persisted state, also touch `src/career_os/db/store.py`
to add a table to the `SCHEMA` block — keep it idempotent (`CREATE TABLE IF
NOT EXISTS`).

## Step 1 — Split UI from data

**Rule the codebase enforces (see `pages/__init__.py`):** pages MUST go
through a UI-free data module, not call `Store` directly. This makes the
data layer testable without `streamlit` installed, and lets `@st.cache_data`
wrap pure functions without leaking widget state.

The split mirrors what already exists:

- `dashboard/queries.py` — read-side queries against the existing tables
  (jobs/scores/drafts/applications). Add a new function here if the new page
  reads existing data.
- `dashboard/todos.py` — full CRUD layer for a single feature (the To-Do plan).
  Mirror this shape if your new page owns its own data: one module with
  `list_*`, `add_*`, `update_*`, `delete_*` functions returning frozen
  dataclasses.

### Adding a new persisted table

Edit the `SCHEMA` triple-string in `src/career_os/db/store.py`. Keep:
- `IF NOT EXISTS` on table + index DDL (the schema is re-run on every
  `Store(...)` instantiation).
- A `created_at` and `updated_at` TEXT column storing ISO-8601 UTC.
- Indexes on whatever columns the page filters by.

Example shape (mirror the `todos` table):

```sql
CREATE TABLE IF NOT EXISTS <name> (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    -- domain columns ...
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_<name>_<col> ON <name>(<col>);
```

Then build the data module with the same helper-function shape as
`dashboard/todos.py`. The `store._conn()` context manager is the only
correct way to talk to SQLite — it commits + closes for you.

## Step 2 — Write the page

Skeleton (compare with `pages/overview.py` for a fully wired example):

```python
"""<name> page — <one-line description>."""
from __future__ import annotations

import streamlit as st

from career_os.config import Settings
from career_os.dashboard import <name> as <name>_lib  # your data module
from career_os.db import Store


def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=60)
def _cached_<thing>() -> list:
    return <name>_lib.list_<thing>(_store())


def render() -> None:
    st.title("<Title>")
    st.caption("<one-line of orientation for the user>")

    with st.sidebar:
        st.header("Filters")
        # widgets that filter the page

    rows = _cached_<thing>()
    if not rows:
        st.info("Nothing here yet. <how to seed data — `career-os ...` command>.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)
```

### Caching rules

- Wrap every data read in `@st.cache_data(ttl=60)`. The Overview page does
  this for every query (`pages/overview.py:24-46`). 60s is the project
  convention — long enough to feel snappy, short enough that a `fetch` in
  another terminal shows up within a minute.
- Cached functions must NOT take `Store` as a parameter — Streamlit can't
  hash it. Re-create the store inside the cached function.
- Add a "🔄 Refresh data" button to the sidebar that calls
  `st.cache_data.clear()` + `st.rerun()` for impatient users.

### Forms inside expanders

If you use `st.form` inside `st.expander`, write it as two `with` blocks
chained with a comma (see `pages/todos.py:100`). The form-clear-on-submit
behavior depends on the form being declared at the page's top level, not
nested deeper than that.

## Step 3 — Register in navigation

Edit `src/career_os/dashboard/app.py`:

```python
from career_os.dashboard.pages import <name>, kpis, overview, todos

PAGES = [
    st.Page(overview.render, title="Overview", icon="📊",
            url_path="overview", default=True),
    # ...existing pages,
    st.Page(<name>.render, title="<Sidebar label>", icon="<emoji>",
            url_path="<name>"),
]
```

Pick an `icon` that's a single emoji (Streamlit renders them in the sidebar).
`url_path` is what shows up in the browser URL — keep it lowercase, no
spaces.

## Step 4 — Test with AppTest

Tests live in `tests/test_dashboard_<name>.py`. The pattern for testing a
single page (without going through the nav) is in `tests/test_dashboard_app.py:68`
— the `_page_harness` helper writes a one-line script that imports your
page and calls `render()`.

Mandatory tests:

```python
from pathlib import Path
import pytest
pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from career_os.db import Store


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


def _page_harness(tmp_path, page_module: str) -> str:
    harness = tmp_path / "harness.py"
    harness.write_text(
        f"from career_os.dashboard.pages.{page_module} import render\nrender()\n"
    )
    return str(harness)


def test_<name>_page_renders_empty(tmp_path, isolated_db):
    harness = _page_harness(tmp_path, "<name>")
    at = AppTest.from_file(harness).run(timeout=15)
    assert not at.exception
    title_text = " ".join(t.value for t in at.title)
    assert "<Title>" in title_text


def test_<name>_page_renders_with_data(tmp_path, isolated_db):
    # seed via the data module, NOT via direct SQL — exercises the layer
    from career_os.dashboard.<name> import add_<thing>
    add_<thing>(isolated_db, ...)
    harness = _page_harness(tmp_path, "<name>")
    at = AppTest.from_file(harness).run(timeout=15)
    assert not at.exception
```

The `pytest.importorskip("streamlit")` line is mandatory — CI runs in two
matrix slots, `[dev]` only and `[dev,dashboard]`. The dashboard tests must
skip cleanly in the pure-`[dev]` run, not fail.

Also write unit tests against the data module directly (no Streamlit
import) under the same file or `tests/test_<name>.py`. Those tests run in
both CI matrix slots.

## Step 5 — Run the suite

```bash
.venv/bin/pytest tests/test_dashboard_<name>.py -v
.venv/bin/ruff check src/career_os/dashboard tests/test_dashboard_<name>.py
```

Then sanity-check the live UI:

```bash
.venv/bin/career-os dashboard
```

Click into your page from the sidebar, confirm rendering with both empty
and seeded data.

## Anti-patterns

- **Don't talk to `Store` from a page.** Always go through a data module.
  `pages/__init__.py` calls this out and the rule exists so the data layer
  stays cacheable + testable.
- **Don't import streamlit in the data module.** That makes it untestable
  without dashboard extras installed.
- **Don't use module-level Streamlit calls.** `st.set_page_config` is the
  one exception — and it lives in `app.py`, not in your page.
- **Don't hardcode the DB path.** Always go through `Settings.load().database_url`
  so tests' `monkeypatch.setenv("DATABASE_URL", ...)` works.
- **Don't add a "delete everything" button.** Destructive actions in the UI
  need confirmation widgets (`st.popover` + a second click). Pattern: see
  the per-row notes popover in `pages/todos.py:195`.
