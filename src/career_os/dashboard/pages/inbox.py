"""Inbox page — HITL action queue.

Every automation that needs the user's attention writes to `actions`. This
page is the human side of the loop: approve / dismiss / defer / snooze.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import streamlit as st

from career_os.actions import (
    SEVERITIES,
    counts_by_severity,
    list_actions,
    resolve,
    run_generators,
    snooze,
)
from career_os.config import Settings
from career_os.db import Store

_KIND_ICONS = {
    "review_job": "🎯",
    "send_draft": "✉️",
    "follow_up": "⏰",
    "review_post": "📝",
    "review_trend": "📡",
    "recheck_stale_source": "🔍",
    "kpi_alert": "📊",
    "dead_backlink": "🔗",
    "stale_pitch": "📨",
    "unlinked_mention": "💬",
}
_SEVERITY_BADGES = {
    "urgent": "🔴 urgent",
    "normal": "🟡 normal",
    "low": "⚪ low",
}


def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=30)
def _cached_actions(kind: str | None, severity: str | None):
    return list_actions(_store(), kind=kind, severity=severity)


@st.cache_data(ttl=30)
def _cached_counts() -> dict[str, int]:
    return counts_by_severity(_store())


def render() -> None:
    st.title("Inbox")
    st.caption(
        "Things the automations think deserve your attention. "
        "Approve to act, dismiss to ignore, defer to revisit, snooze to hide."
    )

    with st.sidebar:
        st.header("Generate")
        st.caption(
            "Re-scan jobs/drafts/applications/posts and create new actions. "
            "Idempotent — re-running won't duplicate open actions."
        )
        if st.button("🤖 Run generators", use_container_width=True, type="primary"):
            counts = run_generators(_store())
            n = sum(counts.values())
            if n == 0:
                st.toast("No new actions", icon="✓")
            else:
                lines = ", ".join(f"{k}: {v}" for k, v in counts.items() if v)
                st.toast(f"{n} actions touched ({lines})", icon="🤖")
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.header("Filters")
        kind_choice = st.selectbox(
            "Kind", options=[
                "(all)", "review_job", "send_draft", "follow_up",
                "review_post", "review_trend", "recheck_stale_source",
                "kpi_alert", "dead_backlink", "stale_pitch",
                "unlinked_mention",
            ],
            key="inbox_kind",
        )
        severity_choice = st.selectbox(
            "Severity", options=["(all)", *SEVERITIES], key="inbox_severity",
        )
        st.divider()
        if st.button("🔄 Refresh", use_container_width=True, key="inbox_refresh"):
            st.cache_data.clear()
            st.rerun()

    counts = _cached_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 Urgent", counts.get("urgent", 0))
    c2.metric("🟡 Normal", counts.get("normal", 0))
    c3.metric("⚪ Low", counts.get("low", 0))
    c4.metric("Total open", sum(counts.values()))

    st.divider()

    filter_kind = None if kind_choice == "(all)" else kind_choice
    filter_severity = None if severity_choice == "(all)" else severity_choice
    actions = _cached_actions(filter_kind, filter_severity)

    if not actions:
        st.info(
            "✅ Inbox zero. Click **🤖 Run generators** in the sidebar to scan "
            "your job/draft/application/post tables for new actions."
        )
        return

    for action in actions:
        _render_action_row(action)


def _render_action_row(action) -> None:
    icon = _KIND_ICONS.get(action.kind, "•")
    badge = _SEVERITY_BADGES.get(action.severity, action.severity)
    with st.container(border=True):
        head_cols = st.columns([0.7, 0.3])
        with head_cols[0]:
            st.markdown(f"### {icon} {action.title}")
            st.caption(f"`{action.kind}`  ·  {badge}")
            if action.description:
                st.write(action.description)
            if action.target_id:
                st.code(f"{action.target_kind}: {action.target_id}", language="text")
            if action.status == "snoozed":
                until = action.snoozed_until
                if until and until > datetime.now(UTC):
                    st.caption(f"😴 snoozed until {until.strftime('%Y-%m-%d %H:%M UTC')}")
        with head_cols[1]:
            _render_action_buttons(action)


def _render_action_buttons(action) -> None:
    btn_cols = st.columns(2)
    if btn_cols[0].button(
        "✅ Approve", key=f"approve_{action.id}", use_container_width=True,
        type="primary",
    ):
        resolve(_store(), action.id, "approved", note="approved via inbox")
        st.cache_data.clear()
        st.toast(f"Approved · {action.kind}", icon="✅")
        st.rerun()
    if btn_cols[1].button(
        "🚫 Dismiss", key=f"dismiss_{action.id}", use_container_width=True,
    ):
        resolve(_store(), action.id, "dismissed", note="dismissed via inbox")
        st.cache_data.clear()
        st.toast(f"Dismissed · {action.kind}", icon="🚫")
        st.rerun()

    btn_cols2 = st.columns(2)
    with btn_cols2[0].popover("⏳ Defer", use_container_width=True):
        st.write(
            "Defer with an optional note (records the decision but "
            "keeps it out of the open queue)."
        )
        note = st.text_input("Note", key=f"defer_note_{action.id}")
        if st.button("Confirm defer", key=f"defer_confirm_{action.id}"):
            resolve(_store(), action.id, "deferred", note=note or None)
            st.cache_data.clear()
            st.rerun()
    with btn_cols2[1].popover("😴 Snooze", use_container_width=True):
        st.write("Hide until a future time. The action re-surfaces automatically.")
        hours = st.slider(
            "Hours", min_value=1, max_value=168, value=24,
            key=f"snooze_hours_{action.id}",
        )
        if st.button("Confirm snooze", key=f"snooze_confirm_{action.id}"):
            snooze(_store(), action.id, datetime.now(UTC) + timedelta(hours=hours))
            st.cache_data.clear()
            st.rerun()
