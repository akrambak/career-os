"""Dashboard pages. Each module exposes a `render()` callable. Register them
in app.py with `st.Page(module.render, title=..., icon=...)`.

To add a new page:
1. Create `pages/your_page.py` with a `render()` function.
2. Import it in app.py and add a `st.Page` entry to the navigation list.
3. Optionally add a unit test under tests/test_dashboard_<name>.py.

Pages share the dashboard's data layer (queries.py + todos.py) — do NOT
talk to the SQLite store directly from a page; go through those modules so
the queries stay testable and cacheable.
"""
