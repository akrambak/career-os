"""Automations page — the bot side of the HITL loop.

Lists every registered automation, lets the user arm/disarm + fire manually,
and shows the audit log of past runs.
"""
from __future__ import annotations

import streamlit as st

from career_os import automations as auto_lib
from career_os.config import Settings
from career_os.db import Store


def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=10)
def _cached_list() -> list:
    return auto_lib.list_automations(_store())


def render() -> None:
    store = _store()
    auto_lib.seed_defaults(store)

    st.title("Automations")
    st.caption(
        "Cron-style schedules layered on top of fetch / score / recheck / "
        "digest / action-generators. Arm what you want to run, fire one "
        "manually with **Run now**."
    )

    with st.sidebar:
        st.header("Runtime")
        if st.button("⚡ Run due now", use_container_width=True, type="primary",
                     help="Fire every armed automation whose next_run_due_at is in the past."):
            results = auto_lib.run_due(store)
            if not results:
                st.toast("Nothing due", icon="✓")
            else:
                ok = sum(1 for r in results.values() if r.status == "ok")
                st.toast(
                    f"{ok}/{len(results)} ok · {len(results) - ok} not-ok",
                    icon="⚡",
                )
            st.cache_data.clear()
            st.rerun()
        st.divider()
        if st.button("🔄 Refresh", use_container_width=True, key="auto_refresh"):
            st.cache_data.clear()
            st.rerun()

    rows = _cached_list()
    if not rows:
        st.info("No automations seeded yet. Restart the dashboard.")
        return

    armed_count = sum(1 for a in rows if a.is_armed)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", len(rows))
    c2.metric("Armed", armed_count)
    c3.metric("Idle", len(rows) - armed_count)

    st.divider()

    for auto in rows:
        _render_automation(auto)


def _render_automation(auto) -> None:
    status_icon = {
        "ok": "🟢", "failed": "🔴", "skipped": "⚪", None: "⚫",
    }.get(auto.last_status, "⚫")
    with st.container(border=True):
        head_cols = st.columns([0.6, 0.4])
        with head_cols[0]:
            armed_badge = "🟢 armed" if auto.is_armed else "⚪ disarmed"
            st.markdown(
                f"### {status_icon} `{auto.name}`  ·  `{auto.kind}`  ·  {armed_badge}"
            )
            next_due = (
                auto.next_run_due_at.strftime("%Y-%m-%d %H:%M UTC")
                if auto.next_run_due_at else "—"
            )
            st.caption(
                f"every {_fmt_interval(auto.interval_minutes)}  ·  "
                f"last: {auto.last_summary or '—'}  ·  "
                f"next due: {next_due}"
            )
        with head_cols[1]:
            _render_action_buttons(auto)

        with st.expander("Config + run log"):
            st.code(_pretty_dict(auto.config), language="json")
            runs = auto_lib.list_runs(_store(), auto.name, limit=10)
            if not runs:
                st.caption("No runs yet.")
            else:
                st.dataframe(
                    [
                        {
                            "started": r.started_at.strftime("%Y-%m-%d %H:%M"),
                            "status": r.status,
                            "summary": r.summary or "—",
                            "error": (r.error_detail or "")[:80],
                        }
                        for r in runs
                    ],
                    use_container_width=True, hide_index=True,
                )


def _render_action_buttons(auto) -> None:
    btn_cols = st.columns(2)
    fire_label = "▶ Run now"
    if btn_cols[0].button(
        fire_label, key=f"fire_{auto.id}", use_container_width=True,
        type="primary",
    ):
        result = auto_lib.fire(_store(), auto.name)
        if result.status == "ok":
            st.toast(f"{auto.name}: {result.summary}", icon="✅")
        elif result.status == "skipped":
            st.toast(f"{auto.name}: skipped — {result.summary}", icon="⏭")
        else:
            st.toast(f"{auto.name} failed: {result.summary}", icon="🔴")
        st.cache_data.clear()
        st.rerun()
    toggle_label = "⏸ Disarm" if auto.is_armed else "▶ Arm"
    if btn_cols[1].button(
        toggle_label, key=f"toggle_{auto.id}", use_container_width=True,
    ):
        auto_lib.set_armed(_store(), auto.name, not auto.is_armed)
        st.cache_data.clear()
        st.rerun()


def _fmt_interval(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:g}h"
    days = hours / 24
    return f"{days:g}d"


def _pretty_dict(d: dict) -> str:
    import json
    return json.dumps(d, indent=2, sort_keys=True)
