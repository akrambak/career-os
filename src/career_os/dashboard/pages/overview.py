"""Overview page — top metrics, top matches, funnel, drafts, source health."""
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from career_os.config import Settings
from career_os.dashboard.focus import compute_focus
from career_os.dashboard.queries import (
    drafts_ready,
    funnel,
    source_health,
    top_matches,
    totals,
)
from career_os.db import Store


def _store() -> Store:
    # See cache note in app.py — Store is per-call by design.
    return Store(Settings.load().database_url)


@st.cache_data(ttl=60)
def _cached_totals() -> dict[str, int]:
    return totals(_store())


@st.cache_data(ttl=60)
def _cached_funnel() -> dict[str, dict[str, int]]:
    return funnel(_store())


@st.cache_data(ttl=60)
def _cached_source_health() -> list:
    return source_health(_store())


@st.cache_data(ttl=60)
def _cached_top_matches(limit: int, min_fit: int, channel: str) -> list:
    return top_matches(_store(), limit=limit, min_fit=min_fit, channel=channel)


@st.cache_data(ttl=60)
def _cached_drafts_ready(limit: int) -> list:
    return drafts_ready(_store(), limit=limit)


@st.cache_data(ttl=30)
def _cached_focus():
    return compute_focus(_store())


def render() -> None:
    st.title("Overview")
    st.caption(
        "AI-agent system that runs my job search + freelance pipeline. "
        "[github.com/akrambak/career-os](https://github.com/akrambak/career-os)"
    )

    # ---- today's focus banner -------------------------------------------
    focus = _cached_focus()
    if focus.headline.startswith("🔴"):
        banner_fn = st.error
    elif focus.headline.startswith("🟡") or focus.headline.startswith("⚡"):
        banner_fn = st.warning
    else:
        banner_fn = st.success
    banner_fn(f"**Today's focus** · {focus.headline}")
    fcols = st.columns(5)
    fcols[0].metric("🔴 urgent", focus.urgent_actions)
    fcols[1].metric("🟡 normal", focus.normal_actions)
    fcols[2].metric("⚡ P0 due ≤7d", focus.p0_todos_due_week)
    fcols[3].metric("📝 ready to post", focus.posts_ready_to_publish)
    fcols[4].metric("⏰ stale apps", focus.stale_applications)
    st.divider()

    with st.sidebar:
        st.header("Filters")
        min_fit = st.slider("Minimum fit score", 0, 100, 60, step=5)
        channel = st.selectbox("Channel", options=["all", "ft", "freelance", "either"])
        limit = st.slider("Rows", 5, 100, 25)
        st.divider()
        if st.button("🔄 Refresh data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        st.caption(f"Last refresh: {datetime.now(UTC).strftime('%H:%M UTC')}")

    t = _cached_totals()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Jobs ingested", f"{t['jobs']:,}")
    c2.metric("Scored", f"{t['scored']:,}")
    c3.metric("Drafts", f"{t['drafts']:,}")
    c4.metric("Applications", f"{t['applications']:,}")

    st.divider()

    left, right = st.columns([2, 1])

    with left:
        st.subheader("Top matches")
        rows = _cached_top_matches(limit=limit, min_fit=min_fit, channel=channel)
        if not rows:
            st.info(
                "No matches at that threshold. "
                "Run `career-os fetch && career-os score` first."
            )
        else:
            st.dataframe(
                [
                    {
                        "fit": r.fit,
                        "channel": r.channel,
                        "title": r.title,
                        "company": r.company or "—",
                        "source": r.source,
                        "comp": r.comp_display,
                        "draft?": "✓" if r.has_draft else "",
                        "stage": r.application_stage or "",
                        "key": r.job_key,
                        "url": r.url,
                    }
                    for r in rows
                ],
                use_container_width=True, hide_index=True,
                column_config={
                    "fit": st.column_config.NumberColumn("fit", width="small"),
                    "url": st.column_config.LinkColumn("link", display_text="open ↗"),
                    "key": st.column_config.TextColumn(width="medium"),
                },
            )
            st.caption(
                "Use the `key` column with the CLI: `career-os draft <key>` · "
                "`career-os apply <key>` · `career-os advance <key>`"
            )

    with right:
        st.subheader("Pipeline funnel")
        f = _cached_funnel()
        for channel_label, channel_key in (("FT", "ft"), ("Freelance", "freelance")):
            channel_counts = f.get(channel_key, {})
            channel_total = sum(channel_counts.values())
            if not channel_counts:
                continue
            max_count = max(channel_counts.values()) or 1
            st.markdown(f"**{channel_label}** · {channel_total} total")
            for stage, count in channel_counts.items():
                filled = int(7 * count / max_count)
                bar = "▓" * filled + "░" * (7 - filled)
                st.write(f"`{stage:<16}` {bar} **{count}**")
            st.write("")

        st.divider()

        st.subheader("Drafts ready to send")
        d = _cached_drafts_ready(limit=10)
        if not d:
            st.info("No untracked drafts. Run `career-os draft --top 5`.")
        else:
            for r in d:
                st.markdown(
                    f"**[{r.fit}]** {r.title[:42]} · _{r.company or '—'}_  \n"
                    f"`{r.job_key}` · {r.channel}",
                )

    st.divider()

    st.subheader("Source health")
    sh = _cached_source_health()
    if not sh:
        st.info("No sources scraped yet. Run `career-os fetch`.")
    else:
        st.dataframe(
            [
                {
                    "source": s.source,
                    "last 24h": s.last_24h,
                    "last 7d": s.last_7d,
                    "total": s.total,
                    "most recent": (
                        s.most_recent.strftime("%Y-%m-%d %H:%M") if s.most_recent else "—"
                    ),
                    "last status": s.status_display,
                    "last fetch": (
                        s.last_fetched_at.strftime("%Y-%m-%d %H:%M")
                        if s.last_fetched_at else "—"
                    ),
                    "closed 7d": s.closed_7d,
                }
                for s in sh
            ],
            use_container_width=True, hide_index=True,
        )
