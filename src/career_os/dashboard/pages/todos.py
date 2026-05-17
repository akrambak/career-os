"""To-Do / Plan page — the 12-week sprint with persistent state."""
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from career_os.config import Settings
from career_os.dashboard import todos as todos_lib
from career_os.dashboard.plan import SECTIONS
from career_os.db import Store

# Priority styling — keep simple, render with markdown badges.
_BADGES = {
    "P0": "🔴 P0",
    "P1": "🟡 P1",
    "P2": "⚪ P2",
}


def _store() -> Store:
    return Store(Settings.load().database_url)


def _ensure_seeded(store: Store) -> None:
    """Seed once per Streamlit session — cheap idempotent check on (section,item)."""
    if st.session_state.get("_plan_seeded"):
        return
    todos_lib.seed_default_plan(store)
    st.session_state["_plan_seeded"] = True


def _toggle_handler(store: Store, todo_id: int, widget_key: str) -> None:
    """Callback used by st.checkbox(on_change=...) — reads the new value from session_state."""
    new_value = st.session_state.get(widget_key, False)
    todos_lib.toggle(store, todo_id, new_value)


def render() -> None:
    store = _store()
    _ensure_seeded(store)

    st.title("To-Do · Career Asset Plan")
    st.caption(
        "Compounding public assets across AI · TypeScript · Blockchain · Trading. "
        "Edit `src/career_os/dashboard/plan.py` to change items — your checked "
        "state and notes survive re-syncing."
    )

    # Banner if plan.py has been edited and the DB still has now-deleted items.
    orphans = todos_lib.count_orphan_seeds(store)
    if orphans:
        banner = st.warning(
            f"📋 {orphans} seeded item(s) in your DB are no longer in the current "
            "plan.py. Click **Sync plan** in the sidebar to apply the latest plan."
        )
        del banner  # silence unused

    # ---- Header KPIs ------------------------------------------------------
    done, total = todos_lib.overall_progress(store)
    pct = (done / total * 100) if total else 0.0
    overdue = sum(1 for t in todos_lib.list_todos(store, open_only=True) if t.is_overdue)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Overall progress", f"{done}/{total}", f"{pct:.0f}%")
    c2.metric("Overdue (P0–P2)", overdue, delta_color="inverse" if overdue else "off")
    c3.metric("Days to deadline", _days_to("2026-08-08"))
    c4.metric("Week #", _current_week_index("2026-05-17"))

    st.progress(pct / 100 if total else 0.0)

    # ---- Sidebar filters --------------------------------------------------
    with st.sidebar:
        st.header("Filters")
        sections_in_db = list(todos_lib.section_progress(store).keys())
        section_choice = st.selectbox(
            "Section", options=["(all)"] + sections_in_db, index=0,
        )
        priority_choice = st.selectbox(
            "Priority", options=["(all)", "P0", "P1", "P2"], index=0,
        )
        open_only = st.toggle("Open only", value=True)
        query = st.text_input("Search", placeholder="laravel, dev.to, …")
        st.divider()
        if st.button(
            "🔄 Sync plan", use_container_width=True,
            help=(
                "Reconciles DB with current plan.py: inserts new, updates "
                "priorities/dates on matching items, removes seeded items no "
                "longer in the plan. Your checked state + notes are preserved."
            ),
        ):
            res = todos_lib.sync_plan(store)
            st.success(
                f"Synced: +{res['inserted']} inserted · "
                f"~{res['updated']} updated · −{res['removed']} removed"
            )
            st.rerun()

        with st.expander("➕ Add ad-hoc item"), st.form("add_todo", clear_on_submit=True):
            new_section = st.selectbox("Section", options=sections_in_db or [SECTIONS[0][0]])
            new_item = st.text_input("Item", max_chars=200)
            new_priority = st.selectbox("Priority", options=["P0", "P1", "P2"], index=1)
            new_due = st.date_input("Due (optional)", value=None)
            submitted = st.form_submit_button("Add")
            if submitted and new_item.strip():
                todos_lib.add_custom(
                    store, section=new_section, item=new_item.strip(),
                    priority=new_priority,
                    due_date=new_due.isoformat() if new_due else None,
                )
                st.toast("Added", icon="✅")
                st.rerun()

    # ---- Today's focus ----------------------------------------------------
    focus = todos_lib.todays_focus(store, horizon_days=7, limit=8)
    if focus:
        with st.expander(f"🎯 This week's focus ({len(focus)} P0 items)", expanded=True):
            for t in focus:
                _render_todo(store, t, key_prefix="focus")
    else:
        st.success("✓ No urgent P0 items in the next 7 days. Use the time to compound.")

    st.divider()

    # ---- Per-section rendering -------------------------------------------
    filter_section = None if section_choice == "(all)" else section_choice
    filter_priority = None if priority_choice == "(all)" else priority_choice
    matches = todos_lib.list_todos(
        store,
        section=filter_section,
        open_only=open_only,
        priority=filter_priority,
        query=query.strip() or None,
    )

    # Group filtered results by section, preserving canonical SECTIONS order.
    by_section: dict[str, list] = {}
    for t in matches:
        by_section.setdefault(t.section, []).append(t)

    canonical_order = [name for name, _ in SECTIONS]
    rendered_sections = [name for name in canonical_order if name in by_section]
    rendered_sections += [name for name in by_section if name not in canonical_order]

    if not rendered_sections:
        st.info("No items match the current filters.")
        return

    section_progress = todos_lib.section_progress(store)
    for section in rendered_sections:
        prog = section_progress.get(section, {"done": 0, "total": 0})
        header = f"{section}  ·  {prog['done']}/{prog['total']}"
        # Default expanded for currently-active phase + always-on sections.
        default_expanded = (
            "Week" in section and prog["done"] < prog["total"]
            or section in {"Daily Habits", "Decision Rules"}
        )
        with st.expander(header, expanded=default_expanded):
            sub = SECTIONS_BY_NAME.get(section)
            if sub:
                st.caption(sub)
            for t in by_section[section]:
                _render_todo(store, t, key_prefix="sec")


def _render_todo(store: Store, t, *, key_prefix: str) -> None:
    """One row: checkbox + label + meta. Notes are editable under a small button."""
    widget_key = f"{key_prefix}_chk_{t.id}"
    if widget_key not in st.session_state:
        st.session_state[widget_key] = t.checked

    cols = st.columns([0.06, 0.74, 0.20])
    with cols[0]:
        st.checkbox(
            "", key=widget_key, label_visibility="collapsed",
            on_change=_toggle_handler, args=(store, t.id, widget_key),
        )
    with cols[1]:
        label = t.item
        if t.checked:
            label = f"~~{label}~~"
        # Append meta
        meta_bits = [_BADGES.get(t.priority, t.priority)]
        if t.due_date:
            days = t.days_until_due
            tag = f"📅 {t.due_date.isoformat()}"
            if days is not None and not t.checked:
                if days < 0:
                    tag = f"⚠️ overdue {abs(days)}d  ·  📅 {t.due_date.isoformat()}"
                elif days <= 2:
                    tag = f"🔥 in {days}d  ·  📅 {t.due_date.isoformat()}"
            meta_bits.append(tag)
        st.markdown(f"{label}  \n*{'  ·  '.join(meta_bits)}*")
    with cols[2], st.popover("notes" if not t.notes else "✎ notes"):
        new_notes = st.text_area(
            "Notes", value=t.notes or "",
            key=f"{key_prefix}_notes_{t.id}", height=120,
            label_visibility="collapsed",
        )
        if new_notes != (t.notes or "") and st.button(
            "Save", key=f"{key_prefix}_savenotes_{t.id}",
        ):
            todos_lib.update_notes(store, t.id, new_notes or None)
            st.toast("Saved", icon="💾")
            st.rerun()
        if not t.is_seed and st.button(
            "🗑 Delete (ad-hoc only)", key=f"{key_prefix}_del_{t.id}",
        ):
            todos_lib.delete_todo(store, t.id)
            st.rerun()


def _days_to(iso_date: str) -> int:
    from datetime import date
    target = date.fromisoformat(iso_date)
    return (target - datetime.now(UTC).date()).days


def _current_week_index(start_iso: str) -> int:
    from datetime import date
    start = date.fromisoformat(start_iso)
    days = (datetime.now(UTC).date() - start).days
    return max(1, days // 7 + 1)


SECTIONS_BY_NAME = {name: sub for name, sub in SECTIONS}
