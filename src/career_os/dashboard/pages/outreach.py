"""Outreach Targets page — link-building pipeline (SEO Feature 2)."""
from __future__ import annotations

import streamlit as st

from career_os import outreach as out_lib
from career_os.config import Settings
from career_os.db import Store
from career_os.outreach.generator import generate_pitch
from career_os.profile import DEFAULT_PROFILE


def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=30)
def _cached_counts() -> dict[str, int]:
    return out_lib.counts_by_stage(_store())


@st.cache_data(ttl=30)
def _cached_list(stage: str | None, category: str | None, min_value: int):
    return out_lib.list_targets(
        _store(), stage=stage, category=category, min_value=min_value,
    )


def render() -> None:
    st.title("Outreach")
    st.caption(
        "Targets you're pitching for backlinks. State machine: "
        "researching → pitched → replied → accepted → published. "
        "Per-category Claude pitches, stale-pitch detection in Inbox."
    )

    settings = Settings.load()
    has_api_key = bool(settings.anthropic_api_key)

    with st.sidebar:
        st.header("Filters")
        stage_choice = st.selectbox(
            "Stage", options=["(all)", *out_lib.STAGES], key="out_stage",
        )
        category_choice = st.selectbox(
            "Category", options=["(all)", *out_lib.CATEGORIES], key="out_cat",
        )
        min_value = st.slider(
            "Min value score", 0, 10, 0, key="out_min_value",
        )
        st.divider()
        if not has_api_key:
            st.info(
                "ANTHROPIC_API_KEY not set — Generate buttons fall back "
                "to per-category templates.",
                icon="ℹ️",
            )
        if st.button("🔄 Refresh", use_container_width=True, key="out_refresh"):
            st.cache_data.clear()
            st.rerun()

    counts = _cached_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📚 Researching", counts.get("researching", 0))
    c2.metric("📨 Pitched", counts.get("pitched", 0))
    c3.metric("💬 Replied", counts.get("replied", 0))
    c4.metric("🟢 Published", counts.get("published", 0))

    st.divider()

    with st.expander(
        "➕ Add outreach target", expanded=sum(counts.values()) == 0,
    ):
        _render_add_form()

    st.divider()

    stage = None if stage_choice == "(all)" else stage_choice
    cat = None if category_choice == "(all)" else category_choice
    rows = _cached_list(stage=stage, category=cat, min_value=min_value)
    if not rows:
        st.info("No targets match the filters. Add one above.")
        return
    for target in rows:
        _render_target_row(target, settings.anthropic_api_key)


def _render_add_form() -> None:
    with st.form("add_target", clear_on_submit=True):
        new_name = st.text_input("Name (memorable label)", key="out_new_name")
        new_site = st.text_input("Site URL", key="out_new_site",
                                 placeholder="https://example.com")
        cc1, cc2 = st.columns(2)
        new_cat = cc1.selectbox(
            "Category", options=out_lib.CATEGORIES, key="out_new_cat",
        )
        new_value = cc2.slider(
            "Value score (1-10)", 1, 10, 5, key="out_new_value",
        )
        new_contact = st.text_input(
            "Contact (email / handle / form URL)", key="out_new_contact",
        )
        new_angle = st.text_area(
            "Pitch angle (one line)", height=80, key="out_new_angle",
            placeholder="The specific reason we fit this target.",
        )
        cc3, cc4 = st.columns(2)
        new_da = cc3.number_input(
            "DA estimate", min_value=0, max_value=100, value=0,
            step=1, key="out_new_da",
        )
        new_target_url = cc4.text_input(
            "Target backlink URL (ours)", key="out_new_target_url",
        )
        new_notes = st.text_area("Notes", height=80, key="out_new_notes")
        submitted = st.form_submit_button("Add target")
        if submitted and new_name.strip() and new_site.strip():
            out_lib.add_target(
                _store(),
                name=new_name, site_url=new_site, category=new_cat,
                contact=new_contact or None,
                pitch_angle=new_angle or None,
                value_score=int(new_value),
                da_estimate=int(new_da) if new_da > 0 else None,
                target_backlink_url=new_target_url or None,
                notes=new_notes or None,
            )
            st.cache_data.clear()
            st.toast("Target added", icon="📌")
            st.rerun()


def _render_target_row(target, api_key: str | None) -> None:
    stage_icon = {
        "researching": "📚", "pitched": "📨", "replied": "💬",
        "accepted": "🤝", "published": "🟢",
        "declined": "🔴", "dropped": "⚪",
    }.get(target.stage, "•")
    da = f"DA {target.da_estimate}" if target.da_estimate else "DA —"
    with st.container(border=True):
        cols = st.columns([0.62, 0.38])
        with cols[0]:
            st.markdown(
                f"### {stage_icon} {target.name}  ·  `{target.category}`"
            )
            st.caption(
                f"value {target.value_score}/10  ·  {da}  ·  "
                f"stage `{target.stage}`  ·  "
                f"updated {target.updated_at.date().isoformat()}"
            )
            if target.pitch_angle:
                st.write(target.pitch_angle)
            st.markdown(f"[open site ↗]({target.site_url})")
            if target.contact:
                st.caption(f"contact: {target.contact}")
        with cols[1]:
            _render_row_actions(target, api_key)

        if target.pitch_draft:
            with st.expander("✉️ Pitch draft", expanded=False):
                st.text_area(
                    "Draft", value=target.pitch_draft,
                    height=200, key=f"out_draft_{target.id}",
                    label_visibility="collapsed",
                )
                st.caption(
                    "Edit manually if needed, then re-save via the **Edit** "
                    "popover. Paste into your email client to send."
                )


def _render_row_actions(target, api_key: str | None) -> None:
    cols = st.columns(2)
    can_advance = target.stage not in out_lib.TERMINAL
    if cols[0].button(
        "✉️ Generate pitch", key=f"out_gen_{target.id}",
        use_container_width=True, type="primary",
        disabled=(target.stage in out_lib.TERMINAL),
        help="Claude drafts a category-specific pitch and saves it on this target.",
    ):
        _do_generate(target, api_key)

    advance_label = "→ next stage"
    if cols[1].button(
        advance_label, key=f"out_adv_{target.id}",
        use_container_width=True, disabled=not can_advance,
    ):
        try:
            out_lib.advance_stage(_store(), target.id)
        except out_lib.StageTransitionError as exc:
            st.warning(str(exc))
        st.cache_data.clear()
        st.rerun()

    cols2 = st.columns(2)
    with cols2[0].popover("Edit", use_container_width=True):
        _render_edit_form(target)
    if cols2[1].button(
        "🗑 Delete", key=f"out_del_{target.id}", use_container_width=True,
    ):
        out_lib.delete_target(_store(), target.id)
        st.cache_data.clear()
        st.rerun()


def _render_edit_form(target) -> None:
    with st.form(f"out_edit_{target.id}", clear_on_submit=False):
        name = st.text_input("Name", value=target.name)
        contact = st.text_input("Contact", value=target.contact or "")
        angle = st.text_area(
            "Pitch angle", value=target.pitch_angle or "", height=80,
        )
        cc1, cc2 = st.columns(2)
        value_score = cc1.slider(
            "Value", 1, 10, target.value_score,
        )
        da = cc2.number_input(
            "DA", min_value=0, max_value=100,
            value=target.da_estimate or 0, step=1,
        )
        target_url = st.text_input(
            "Target backlink URL", value=target.target_backlink_url or "",
        )
        notes = st.text_area("Notes", value=target.notes or "", height=80)
        save = st.form_submit_button("Save")
        if save:
            out_lib.update_target(
                _store(), target.id,
                name=name, contact=contact or None,
                pitch_angle=angle or None,
                value_score=int(value_score),
                da_estimate=int(da) if da > 0 else None,
                target_backlink_url=target_url or None,
                notes=notes or None,
            )
            st.cache_data.clear()
            st.toast("Saved", icon="💾")
            st.rerun()
    # Quick stage shortcuts (decline / drop / mark published)
    sc1, sc2, sc3 = st.columns(3)
    if sc1.button("Mark declined", key=f"out_decline_{target.id}"):
        out_lib.advance_stage(_store(), target.id, to="declined")
        st.cache_data.clear()
        st.rerun()
    if sc2.button("Mark dropped", key=f"out_dropped_{target.id}"):
        out_lib.advance_stage(_store(), target.id, to="dropped")
        st.cache_data.clear()
        st.rerun()
    if sc3.button("Mark published", key=f"out_pub_{target.id}",
                  type="primary"):
        out_lib.advance_stage(_store(), target.id, to="published")
        st.cache_data.clear()
        st.rerun()


def _do_generate(target, api_key: str | None) -> None:
    with st.spinner(f"Drafting {target.category} pitch..."):
        result = generate_pitch(
            api_key=api_key, target=target, profile=DEFAULT_PROFILE,
            dry_run=not api_key,
        )
    if result.is_no_fit:
        st.warning(
            f"Claude declined: {result.no_fit_reason or '—'}",
            icon="🛑",
        )
        return
    out_lib.update_target(
        _store(), target.id, pitch_draft=result.body,
    )
    st.cache_data.clear()
    st.toast(f"Pitch saved · model={result.model}", icon="✉️")
    st.rerun()
