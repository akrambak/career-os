"""KPIs page — reputation + career metrics with weekly snapshots.

Per-week value + threshold-driven green/red badge + 28-day rolling trend.
Derived KPIs auto-fill from queries; manual ones get an entry form.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import streamlit as st

from career_os.config import Settings
from career_os.db import Store
from career_os.kpi import (
    KPIS,
    compute_derived,
    get_snapshot,
    list_recent,
    sync_derived,
    upsert_snapshot,
)


def _store() -> Store:
    return Store(Settings.load().database_url)


def _monday() -> date:
    d = datetime.now(UTC).date()
    return d - timedelta(days=d.weekday())


@st.cache_data(ttl=60)
def _cached_derived() -> dict:
    return compute_derived(_store())


def render() -> None:
    st.title("KPIs")
    st.caption(
        "Career + reputation metrics tracked weekly. Decision-rule badges "
        "from the plan: 🟢 above threshold, 🔴 below — act on red."
    )

    with st.sidebar:
        st.header("Snapshot")
        if st.button("🔄 Sync derived now", use_container_width=True,
                     type="primary"):
            n = sync_derived(_store())
            st.toast(f"Synced {n} derived KPI(s)", icon="✅")
            st.cache_data.clear()
            st.rerun()
        st.divider()
        if st.button("🔄 Refresh view", use_container_width=True, key="kpi_refresh"):
            st.cache_data.clear()
            st.rerun()

    derived = _cached_derived()
    mon = _monday()

    for tier in (1, 2, 3):
        st.subheader(f"Tier {tier} — {_tier_label(tier)}")
        for kpi in (k for k in KPIS if k.tier == tier):
            _render_kpi_row(kpi, mon, derived)
        st.write("")


def _tier_label(tier: int) -> str:
    return {
        1: "Compounding career assets",
        2: "Conversion (pipeline metrics)",
        3: "Revenue (signed work + runway)",
    }[tier]


def _render_kpi_row(kpi, mon: date, derived: dict) -> None:
    snap = get_snapshot(_store(), kpi.key, mon)
    # Prefer a fresh derived value over a stale snapshot for derived KPIs.
    if kpi.source == "derived":
        value = derived.get(kpi.key)
        if value is not None and (snap is None or snap.value != value):
            snap = upsert_snapshot(
                _store(), kpi_key=kpi.key, value=value,
                week_start=mon, source="derived",
            )

    with st.container(border=True):
        head_cols = st.columns([0.45, 0.20, 0.20, 0.15])
        with head_cols[0]:
            st.markdown(f"**{kpi.label}**  ·  `{kpi.source}`")
            st.caption(kpi.note)
        with head_cols[1]:
            if snap is None:
                st.metric("this week", "—")
            else:
                st.metric(
                    "this week",
                    _fmt_value(snap.value, kpi.unit),
                )
        with head_cols[2]:
            if kpi.threshold is not None:
                badge = "—"
                if snap is not None:
                    badge = "🟢" if kpi.threshold.is_green(snap.value) else "🔴"
                st.metric(
                    f"target {kpi.threshold.display()}",
                    badge,
                )
        with head_cols[3]:
            _render_trend_sparkline(kpi)

        if kpi.source == "manual":
            with st.expander("✏️ Enter / update this week"):
                _render_manual_form(kpi, mon, snap)


def _render_trend_sparkline(kpi) -> None:
    recent = list_recent(_store(), kpi.key, weeks=8)
    if not recent:
        st.caption("no history")
        return
    # newest-first → reverse for ASCII bars
    recent = list(reversed(recent))
    max_v = max((r.value for r in recent), default=1.0) or 1.0
    bars = "".join(_block(r.value / max_v) for r in recent)
    st.caption(f"`{bars}` 8wk")


def _block(ratio: float) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    idx = min(len(blocks) - 1, int(ratio * (len(blocks) - 1)))
    return blocks[idx]


def _render_manual_form(kpi, mon: date, snap) -> None:
    with st.form(f"kpi_form_{kpi.key}", clear_on_submit=False):
        current = float(snap.value) if snap else 0.0
        new_value = st.number_input(
            f"Value ({kpi.unit or 'unit'})",
            value=current, step=1.0, format="%g",
            key=f"kpi_value_{kpi.key}",
        )
        new_notes = st.text_input(
            "Notes (optional)",
            value=snap.notes if snap and snap.notes else "",
            key=f"kpi_notes_{kpi.key}",
        )
        submitted = st.form_submit_button("Save")
        if submitted:
            upsert_snapshot(
                _store(), kpi_key=kpi.key, value=new_value,
                week_start=mon, source="manual",
                notes=new_notes or None,
            )
            st.cache_data.clear()
            st.toast(f"{kpi.label} updated", icon="✅")
            st.rerun()


def _fmt_value(value: float, unit: str) -> str:
    if unit == "%":
        return f"{value * 100:.1f}%" if value <= 1 else f"{value:.1f}%"
    if unit == "EUR":
        return f"€{value:,.0f}"
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.1f}"
