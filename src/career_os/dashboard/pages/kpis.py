"""KPIs page — placeholder for the Tier 1/2/3 metrics (section II of the plan).

Wire-up plan when prioritized:
- New `kpi_snapshots` table: (week_start, kpi_key, value, target, computed_or_manual)
- Auto-fill what queries.py can derive (inbounds, applications, source counts)
- Manual entry form for the rest (LinkedIn impressions, GitHub stars,
  cold-pitch reply rate, etc.)
- Trend chart per KPI (28-day rolling)
- Decision-rule badges next to each row (green if above threshold)
"""
from __future__ import annotations

import streamlit as st


def render() -> None:
    st.title("KPIs")
    st.caption("Tier 1 (compounding) · Tier 2 (conversion) · Tier 3 (revenue).")

    st.info(
        "**Not yet wired.** This page is a stub demonstrating the extension "
        "pattern: see `pages/kpis.py` and `pages/__init__.py` for the recipe. "
        "The data model lives in the plan under section II — implementation "
        "is tracked in the To-Do page under 'Dashboard Improvements'."
    )

    # Static preview of the intended layout so we can iterate on it.
    st.subheader("Tier 1 — Compounding (preview)")
    st.dataframe(
        [
            {"kpi": "Qualified inbounds / wk", "target by Aug 8": 5, "this week": "—"},
            {"kpi": "Reply rate (cold)", "target by Aug 8": "12%", "this week": "—"},
            {"kpi": "LinkedIn impressions (28d)", "target by Aug 8": "50k", "this week": "—"},
            {"kpi": "GitHub stars", "target by Aug 8": 50, "this week": "—"},
            {"kpi": "dev.to avg reading time / post", "target by Aug 8": "3min", "this week": "—"},
        ],
        use_container_width=True, hide_index=True,
    )

    st.subheader("Tier 2 — Conversion (preview)")
    st.dataframe(
        [
            {"kpi": "Outreach sent / wk", "decision threshold": "<30 = not doing the work"},
            {"kpi": "Calls booked / wk", "decision threshold": "<2 by wk 4 = positioning broken"},
            {"kpi": "Call → proposal %", "decision threshold": "<40% = call shape wrong"},
            {"kpi": "Proposal → signed %", "decision threshold": "<30% = price/scope wrong"},
            {"kpi": "First contact → signed (days)", "decision threshold": ">35 = drop"},
        ],
        use_container_width=True, hide_index=True,
    )

    st.subheader("Tier 3 — Revenue (preview)")
    st.dataframe(
        [
            {"kpi": "Pipeline value (weighted)", "threshold": "€20k by wk 6"},
            {"kpi": "MRR committed", "threshold": "€3k by wk 10"},
            {"kpi": "Runway days from signed work", "threshold": "90 by wk 12"},
        ],
        use_container_width=True, hide_index=True,
    )
