"""Trends page — real-time signal feed + per-channel post generator.

Scrape HN / dev.to / Tavily; rank by signal_score; click a trend to spawn
a Claude-drafted post in the Posts table with `trend_id` set. The user
then reviews / edits / ships from the Posts page.
"""
from __future__ import annotations

import asyncio

import streamlit as st

from career_os.config import Settings
from career_os.dashboard import posts as posts_lib
from career_os.db import Store
from career_os.profile import DEFAULT_PROFILE
from career_os.trends import (
    SOURCES,
    counts_by_source,
    list_trends,
    mark_used,
)
from career_os.trends.generator import (
    CHANNEL_TARGETS,
    CHANNELS,
    generate_post,
)
from career_os.trends.sources import scan_sources


def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=30)
def _cached_counts() -> dict[str, int]:
    return counts_by_source(_store())


@st.cache_data(ttl=30)
def _cached_trends(source: str | None, min_signal: float, hide_used: bool, limit: int):
    return list_trends(
        _store(), source=source, min_signal=min_signal,
        hide_used=hide_used, limit=limit,
    )


def render() -> None:
    st.title("Trends")
    st.caption(
        "Real-time signal from HN, dev.to and web search. Click a channel "
        "button to draft a post anchored in the trend — review on the Posts page."
    )

    settings = Settings.load()
    has_api_key = bool(settings.anthropic_api_key)

    with st.sidebar:
        st.header("Scan")
        if st.button("🔍 Scan now", use_container_width=True, type="primary",
                     help="Refresh HN + dev.to (+ Tavily if TAVILY_API_KEY set)."):
            with st.spinner("Scanning sources..."):
                results = asyncio.run(scan_sources(_store(), DEFAULT_PROFILE))
            n = sum(results.values())
            tavily_note = (
                "" if settings.tavily_api_key
                else " (Tavily skipped — TAVILY_API_KEY not set)"
            )
            st.toast(f"{n} trends touched{tavily_note}", icon="🔍")
            st.cache_data.clear()
            st.rerun()
        st.divider()
        st.header("Filters")
        source_choice = st.selectbox(
            "Source", options=["(all)", *SOURCES], key="trends_source",
        )
        min_signal = st.slider(
            "Min signal", 0.0, 5.0, 1.5, step=0.1, key="trends_min_signal",
        )
        hide_used = st.toggle(
            "Hide already-used trends", value=True, key="trends_hide_used",
        )
        limit = st.slider("Rows", 5, 100, 30, key="trends_limit")
        st.divider()
        if not has_api_key:
            st.info(
                "ANTHROPIC_API_KEY not set — generator buttons use the "
                "dry-run template (still creates posts you can edit).",
                icon="ℹ️",
            )
        if st.button("🔄 Refresh", use_container_width=True, key="trends_refresh"):
            st.cache_data.clear()
            st.rerun()

    counts = _cached_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("HN", counts.get("hn", 0))
    c2.metric("dev.to", counts.get("devto", 0))
    c3.metric("Tavily", counts.get("tavily", 0))
    c4.metric("Total", sum(counts.values()))

    st.divider()

    filter_source = None if source_choice == "(all)" else source_choice
    trends = _cached_trends(filter_source, min_signal, hide_used, limit)

    if not trends:
        st.info(
            "Nothing above the signal threshold yet. Lower the slider, "
            "uncheck 'Hide used', or click **🔍 Scan now** in the sidebar."
        )
        return

    for trend in trends:
        _render_trend_row(trend, has_api_key, settings.anthropic_api_key)


def _render_trend_row(trend, has_api_key: bool, api_key: str | None) -> None:
    source_emoji = {
        "hn": "📰", "devto": "📝", "tavily": "🌐",
        "reddit": "🤖", "manual": "✋",
    }.get(trend.source, "•")
    used_badge = "  ✓ used" if trend.used_at else ""
    with st.container(border=True):
        head_cols = st.columns([0.66, 0.34])
        with head_cols[0]:
            st.markdown(
                f"### `[{trend.signal_score:.1f}]` {source_emoji} "
                f"**{trend.title}**{used_badge}"
            )
            meta = [
                f"{trend.score} points",
                f"{trend.comment_count} comments",
                trend.fetched_at.strftime("%Y-%m-%d %H:%M"),
            ]
            if trend.tags:
                meta.append(", ".join(trend.tags[:5]))
            st.caption("  ·  ".join(meta))
            if trend.summary:
                st.write(trend.summary[:280] + ("…" if len(trend.summary) > 280 else ""))
            st.markdown(f"[open ↗]({trend.url})")
        with head_cols[1]:
            _render_generate_buttons(trend, api_key)


def _render_generate_buttons(trend, api_key: str | None) -> None:
    """4 per-channel buttons. Each spawns a draft on the Posts page."""
    btn_cols = st.columns(2)
    for i, channel in enumerate(CHANNELS):
        target = CHANNEL_TARGETS.get(channel, "")
        col = btn_cols[i % 2]
        if col.button(
            f"→ {channel}", key=f"gen_{trend.id}_{channel}",
            use_container_width=True,
            help=f"Generate a {channel} draft ({target}). Lands on Posts.",
        ):
            _do_generate(trend, channel, api_key)


def _do_generate(trend, channel: str, api_key: str | None) -> None:
    with st.spinner(f"Drafting {channel} post via Claude..."):
        result = generate_post(
            api_key=api_key, trend=trend, channel=channel,
            profile=DEFAULT_PROFILE,
            dry_run=not api_key,
        )
    if result.is_no_fit:
        st.warning(
            f"Claude declined this trend for {channel}: {result.no_fit_reason or '—'}",
            icon="🛑",
        )
        return
    title = _derive_post_title(trend, channel)
    new_post = posts_lib.add_post(
        _store(), title=title, channel=channel, body=result.body,
        notes=f"Generated from trend #{trend.id} ({trend.source}) · model={result.model}",
    )
    # Attach trend_id (migrated column) directly via raw SQL — posts_lib
    # doesn't expose it as a typed field and we don't need to overhaul that
    # module just for this link.
    with _store()._conn() as c:  # noqa: SLF001
        c.execute(
            "UPDATE posts SET trend_id = ? WHERE id = ?",
            (trend.id, new_post.id),
        )
    mark_used(_store(), trend.id)
    st.cache_data.clear()
    st.toast(
        f"Draft created on Posts page · {channel}",
        icon="✏️",
    )


def _derive_post_title(trend, channel: str) -> str:
    """Working title for the draft. User edits later."""
    prefix = {
        "x": "🐦", "linkedin": "💼", "devto": "📝", "blog": "📰",
    }.get(channel, channel)
    return f"{prefix} {trend.title}"[:200]
