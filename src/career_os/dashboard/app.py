"""Streamlit dashboard. Launch with: `career-os dashboard`."""
from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from ..config import Settings
from ..db import Store
from .queries import (
    drafts_ready,
    funnel,
    source_health,
    top_matches,
    totals,
)

st.set_page_config(
    page_title="Career-OS",
    page_icon="🎯",
    layout="wide",
)


@st.cache_resource
def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=60)
def _cached_totals() -> dict[str, int]:
    return totals(_store())


@st.cache_data(ttl=60)
def _cached_funnel() -> dict[str, int]:
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


def main() -> None:
    st.title("Career-OS")
    st.caption(
        "AI-agent system that runs my job search + freelance pipeline. "
        "[github.com/akrambak/career-os](https://github.com/akrambak/career-os)"
    )

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
                        "comp": r.compensation or "—",
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
        total = sum(f.values())
        max_count = max(f.values()) or 1
        for stage, count in f.items():
            bar = "▓" * int(7 * count / max_count) + "░" * (7 - int(7 * count / max_count))
            st.write(f"`{stage:<10}` {bar} **{count}**")
        st.caption(f"Total: {total}")

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
                }
                for s in sh
            ],
            use_container_width=True, hide_index=True,
        )


if __name__ == "__main__":
    main()
