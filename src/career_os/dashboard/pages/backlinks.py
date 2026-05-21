"""Backlinks page — inventory + health (SEO Feature 1)."""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import streamlit as st

from career_os import backlinks as bl_lib
from career_os.backlinks.recheck import recheck_all, summarize
from career_os.config import Settings
from career_os.db import Store


def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=30)
def _cached_counts() -> dict[str, int]:
    return bl_lib.counts_by_status(_store())


@st.cache_data(ttl=30)
def _cached_dofollow_ratio() -> float:
    return bl_lib.dofollow_ratio(_store())


@st.cache_data(ttl=30)
def _cached_unique_domains() -> int:
    return bl_lib.unique_referring_domains(_store())


@st.cache_data(ttl=30)
def _cached_list(status: str | None, rel: str | None, min_da: int) -> list:
    return bl_lib.list_backlinks(
        _store(), status=status, rel=rel, min_da=min_da or None, limit=300,
    )


def render() -> None:
    st.title("Backlinks")
    st.caption(
        "Every external page linking TO us. Weekly recheck flips dead "
        "links to `dead`/`removed`; the Inbox surfaces them so you can "
        "reach out or update the source."
    )

    with st.sidebar:
        st.header("Recheck")
        if st.button(
            "🔍 Recheck due now", use_container_width=True, type="primary",
            help="Walks live backlinks not checked in 7+ days, "
                 "issues a GET each, updates status.",
        ):
            with st.spinner("Rechecking backlinks..."):
                outcomes = asyncio.run(recheck_all(_store(), limit=200))
            s = summarize(outcomes)
            st.toast(
                f"{len(outcomes)} checked · " + " · ".join(
                    f"{k}:{v}" for k, v in s.items()
                ),
                icon="🔍",
            )
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.header("Filters")
        status_choice = st.selectbox(
            "Status", options=["(all)", *bl_lib.STATUSES], key="bl_status",
        )
        rel_choice = st.selectbox(
            "Rel", options=["(all)", *bl_lib.REL_VALUES], key="bl_rel",
        )
        min_da = st.slider("Min DA", 0, 100, 0, step=5, key="bl_min_da")
        st.divider()
        if st.button("🔄 Refresh view", use_container_width=True, key="bl_refresh"):
            st.cache_data.clear()
            st.rerun()

    counts = _cached_counts()
    live = counts.get("live", 0)
    dead = counts.get("dead", 0) + counts.get("removed", 0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🟢 Live", live)
    c2.metric("🔴 Dead/Removed", dead)
    c3.metric("Dofollow ratio", f"{_cached_dofollow_ratio() * 100:.0f}%")
    c4.metric("Referring domains", _cached_unique_domains())

    st.divider()

    with st.expander("➕ Add backlink (manual)", expanded=live == 0):
        _render_add_form()

    st.divider()

    status = None if status_choice == "(all)" else status_choice
    rel = None if rel_choice == "(all)" else rel_choice
    rows = _cached_list(status=status, rel=rel, min_da=min_da)
    if not rows:
        st.info(
            "No backlinks match the filters. Add one above or run a "
            "Mention Hunter scan (Mentions page) to auto-discover candidates."
        )
        return
    for bl in rows:
        _render_backlink_row(bl)


def _render_add_form() -> None:
    with st.form("add_backlink", clear_on_submit=True):
        source_url = st.text_input(
            "Source URL (the page linking TO us)", key="bl_new_source",
            placeholder="https://example.com/article",
        )
        target_url = st.text_input(
            "Target URL (our page being linked to)", key="bl_new_target",
            placeholder="https://bak-dev.com/blog/career-os",
        )
        cc1, cc2, cc3 = st.columns([2, 1, 1])
        anchor = cc1.text_input("Anchor text", key="bl_new_anchor")
        rel = cc2.selectbox("Rel", options=bl_lib.REL_VALUES, key="bl_new_rel")
        da = cc3.number_input(
            "DA estimate", min_value=0, max_value=100, value=0,
            step=1, key="bl_new_da",
        )
        notes = st.text_area("Notes", key="bl_new_notes", height=80)
        submitted = st.form_submit_button("Add backlink")
        if submitted and source_url.strip() and target_url.strip():
            bl_lib.upsert_backlink(
                _store(),
                source_url=source_url.strip(),
                target_url=target_url.strip(),
                anchor_text=anchor.strip() or None,
                rel=rel,
                da_estimate=int(da) if da > 0 else None,
                discovered_via="manual",
                notes=notes.strip() or None,
            )
            st.cache_data.clear()
            st.toast("Backlink saved", icon="🔗")
            st.rerun()


def _render_backlink_row(bl) -> None:
    status_icon = {
        "live": "🟢", "redirect": "🟡", "removed": "⚪",
        "dead": "🔴", "unverified": "❔",
    }.get(bl.status, "•")
    rel_badge = {
        "dofollow": "🟢 dofollow", "nofollow": "⚪ nofollow",
        "ugc": "🟡 ugc", "sponsored": "🟠 sponsored",
    }.get(bl.rel, bl.rel)
    da_badge = f"DA {bl.da_estimate}" if bl.da_estimate else "DA —"
    with st.container(border=True):
        cols = st.columns([0.66, 0.34])
        with cols[0]:
            st.markdown(
                f"### {status_icon} `{urlparse(bl.source_url).hostname or '—'}`"
                f"  ·  {rel_badge}  ·  {da_badge}"
            )
            st.caption(
                f"→ {bl.target_url}  ·  "
                f"anchor: {bl.anchor_text or '(none)'}  ·  "
                f"first seen {bl.first_seen_at.date().isoformat()}"
            )
            st.markdown(f"[open source ↗]({bl.source_url})")
            if bl.notes:
                st.caption(bl.notes)
        with cols[1]:
            _render_row_actions(bl)


def _render_row_actions(bl) -> None:
    cols = st.columns(2)
    with cols[0].popover("Edit rel/status", use_container_width=True):
        new_rel = st.selectbox(
            "Rel", options=bl_lib.REL_VALUES,
            index=bl_lib.REL_VALUES.index(bl.rel) if bl.rel in bl_lib.REL_VALUES else 0,
            key=f"bl_edit_rel_{bl.id}",
        )
        new_status = st.selectbox(
            "Status", options=bl_lib.STATUSES,
            index=bl_lib.STATUSES.index(bl.status) if bl.status in bl_lib.STATUSES else 0,
            key=f"bl_edit_status_{bl.id}",
        )
        if st.button("Apply", key=f"bl_apply_{bl.id}"):
            if new_rel != bl.rel:
                bl_lib.update_rel(_store(), bl.id, new_rel)
            if new_status != bl.status:
                bl_lib.update_status(_store(), bl.id, new_status)
            st.cache_data.clear()
            st.rerun()
    if cols[1].button(
        "🗑 Delete", key=f"bl_del_{bl.id}", use_container_width=True,
    ):
        bl_lib.delete_backlink(_store(), bl.id)
        st.cache_data.clear()
        st.rerun()
