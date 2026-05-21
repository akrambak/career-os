"""Mentions page — auto-discovered brand references (SEO Feature 3)."""
from __future__ import annotations

import asyncio

import streamlit as st

from career_os import mentions as men_lib
from career_os.config import Settings
from career_os.db import Store
from career_os.mentions.sources import scan_sources


def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=30)
def _cached_counts() -> dict[str, int]:
    return men_lib.counts_by_status(_store())


@st.cache_data(ttl=30)
def _cached_list(status: str | None, source: str | None,
                 has_link_value: bool | None):
    return men_lib.list_mentions(
        _store(), status=status, source=source,
        has_link_value=has_link_value,
    )


def render() -> None:
    st.title("Mentions")
    st.caption(
        "Auto-discovered references to your brand / repo / domain. "
        "Unlinked mentions are the highest-ROI link-building work — "
        "convert each to a real backlink, or spawn a directed outreach pitch."
    )

    settings = Settings.load()
    has_github_token = bool(settings.github_token)

    with st.sidebar:
        st.header("Scan")
        if st.button(
            "🔍 Scan now", use_container_width=True, type="primary",
            help="Refreshes HN + dev.to (+ GitHub code search if "
                 "GITHUB_TOKEN set).",
        ):
            with st.spinner("Scanning mention sources..."):
                results = asyncio.run(scan_sources(_store()))
            n = sum(results.values())
            gh_note = "" if has_github_token else " (GitHub skipped — token unset)"
            st.toast(f"{n} mentions touched{gh_note}", icon="🔍")
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.header("Filters")
        status_choice = st.selectbox(
            "Status", options=["(all)", *men_lib.STATUSES],
            index=1,  # default to 'open'
            key="men_status",
        )
        source_choice = st.selectbox(
            "Source", options=["(all)", *men_lib.SOURCES], key="men_source",
        )
        link_choice = st.selectbox(
            "Linked?",
            options=["(any)", "unlinked (no backlink)", "linked"],
            key="men_link",
        )
        st.divider()
        if st.button("🔄 Refresh", use_container_width=True, key="men_refresh"):
            st.cache_data.clear()
            st.rerun()

    counts = _cached_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔓 Open", counts.get("open", 0))
    c2.metric("✅ Converted", counts.get("converted", 0))
    c3.metric("🔗 Linked", counts.get("linked", 0))
    c4.metric("🚫 Dismissed", counts.get("dismissed", 0))

    st.divider()

    with st.expander("➕ Add mention (manual)", expanded=False):
        _render_add_form()

    st.divider()

    status = None if status_choice == "(all)" else status_choice
    source = None if source_choice == "(all)" else source_choice
    has_link_filter: bool | None = None
    if link_choice == "linked":
        has_link_filter = True
    elif link_choice == "unlinked (no backlink)":
        has_link_filter = False

    rows = _cached_list(status=status, source=source,
                       has_link_value=has_link_filter)
    if not rows:
        st.info(
            "No mentions match the filters. Hit **🔍 Scan now** to run an "
            "HN + dev.to search across your tracked terms."
        )
        return
    for mention in rows:
        _render_mention_row(mention)


def _render_add_form() -> None:
    with st.form("add_mention", clear_on_submit=True):
        new_source = st.selectbox(
            "Source", options=men_lib.SOURCES, key="men_new_source",
        )
        new_url = st.text_input(
            "Source URL", key="men_new_url",
            placeholder="https://example.com/article-mentioning-us",
        )
        new_term = st.text_input(
            "Matched term", key="men_new_term",
            placeholder="bak-dev.com / Career-OS / AkBak",
        )
        new_snippet = st.text_area(
            "Context snippet", key="men_new_snippet", height=80,
            placeholder="The sentence(s) around the mention.",
        )
        new_has_link = st.toggle(
            "Already linked back to us?", value=False,
            key="men_new_has_link",
        )
        submitted = st.form_submit_button("Add mention")
        if submitted and new_url.strip() and new_term.strip():
            men_lib.upsert_mention(
                _store(),
                source=new_source, source_url=new_url.strip(),
                matched_term=new_term.strip(),
                context_snippet=new_snippet.strip() or None,
                has_link_value=bool(new_has_link),
            )
            st.cache_data.clear()
            st.toast("Mention saved", icon="💬")
            st.rerun()


def _render_mention_row(mention) -> None:
    source_emoji = {
        "hn": "📰", "devto": "📝", "github": "🐙",
        "reddit": "🤖", "tavily": "🌐", "manual": "✋",
    }.get(mention.source, "•")
    link_badge = "🔗 linked" if mention.has_link else "🔓 UNLINKED"
    with st.container(border=True):
        cols = st.columns([0.66, 0.34])
        with cols[0]:
            st.markdown(
                f"### {source_emoji} `{mention.matched_term}`  ·  {link_badge}"
            )
            st.caption(
                f"status: `{mention.status}`  ·  "
                f"discovered {mention.discovered_at.date().isoformat()}"
            )
            if mention.context_snippet:
                st.write(mention.context_snippet)
            st.markdown(f"[open source ↗]({mention.source_url})")
        with cols[1]:
            _render_actions(mention)


def _render_actions(mention) -> None:
    is_open = mention.status == "open"
    cols = st.columns(2)
    with cols[0].popover(
        "🔗 Convert", use_container_width=True, disabled=not is_open,
    ):
        st.write(
            "Promote this mention to a `backlinks` row. Use this AFTER "
            "you've asked the publisher to add the link and they have."
        )
        target_url = st.text_input(
            "Our target URL (where the link points)",
            value="https://github.com/akrambak/career-os",
            key=f"men_conv_target_{mention.id}",
        )
        anchor = st.text_input(
            "Anchor text",
            value=mention.matched_term,
            key=f"men_conv_anchor_{mention.id}",
        )
        rel = st.selectbox(
            "Rel", options=("dofollow", "nofollow", "ugc", "sponsored"),
            key=f"men_conv_rel_{mention.id}",
        )
        da = st.number_input(
            "DA estimate", min_value=0, max_value=100, value=0, step=1,
            key=f"men_conv_da_{mention.id}",
        )
        if st.button("Confirm convert", key=f"men_conv_btn_{mention.id}",
                    type="primary"):
            men_lib.convert_to_backlink(
                _store(), mention.id,
                target_url=target_url, anchor_text=anchor or None,
                rel=rel, da_estimate=int(da) if da > 0 else None,
            )
            st.cache_data.clear()
            st.toast("Converted → backlinks", icon="✅")
            st.rerun()

    with cols[1].popover(
        "📨 To outreach", use_container_width=True, disabled=not is_open,
    ):
        st.write(
            "Spawn an Outreach target so you can pitch the publisher to "
            "add the link. Lands on the Outreach page in 'researching'."
        )
        angle = st.text_input(
            "Pitch angle (1 line)",
            value="Thanks for the mention — open to adding a link?",
            key=f"men_to_out_angle_{mention.id}",
        )
        value = st.slider(
            "Value score", 1, 10, 6, key=f"men_to_out_value_{mention.id}",
        )
        target_url = st.text_input(
            "Target backlink URL (ours)",
            value="https://github.com/akrambak/career-os",
            key=f"men_to_out_target_{mention.id}",
        )
        if st.button("Create outreach", key=f"men_to_out_btn_{mention.id}",
                    type="primary"):
            men_lib.to_outreach_target(
                _store(), mention.id,
                pitch_angle=angle or None,
                value_score=int(value),
                target_backlink_url=target_url or None,
            )
            st.cache_data.clear()
            st.toast("Outreach target created", icon="📨")
            st.rerun()

    cols2 = st.columns(2)
    if cols2[0].button(
        "🚫 Dismiss", key=f"men_dismiss_{mention.id}",
        use_container_width=True, disabled=not is_open,
    ):
        men_lib.set_status(_store(), mention.id, "dismissed")
        st.cache_data.clear()
        st.rerun()
    if cols2[1].button(
        "🗑 Delete", key=f"men_del_{mention.id}", use_container_width=True,
    ):
        men_lib.delete_mention(_store(), mention.id)
        st.cache_data.clear()
        st.rerun()
