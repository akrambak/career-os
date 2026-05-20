"""Ideas page — raw seed jottings for future posts/content."""
from __future__ import annotations

import streamlit as st

from career_os.config import Settings
from career_os.dashboard import ideas as ideas_lib
from career_os.dashboard.ideas import CHANNELS
from career_os.db import Store
from career_os.presence import (
    list_brainstorm_sessions,
    read_idea_body,
    spawn_brainstorm_session,
)


def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=60)
def _cached_ideas(channel: str | None, include_archived: bool) -> list:
    return ideas_lib.list_ideas(
        _store(), channel=channel, include_archived=include_archived,
    )


@st.cache_data(ttl=60)
def _cached_counts() -> dict[str, int]:
    return ideas_lib.counts_by_channel(_store())


def render() -> None:
    st.title("Ideas")
    st.caption(
        "Raw seed jottings — title + hook + channel target. "
        "Promote to a draft manually on the Posts page when ready."
    )

    with st.sidebar:
        st.header("Filters")
        channel_choice = st.selectbox(
            "Channel", options=["(all)", *CHANNELS], index=0, key="ideas_channel_filter",
        )
        include_archived = st.toggle("Show archived", value=False, key="ideas_show_arch")
        st.divider()
        if st.button("🔄 Refresh", use_container_width=True, key="ideas_refresh"):
            st.cache_data.clear()
            st.rerun()

    counts = _cached_counts()
    total_active = sum(counts.values())
    cols = st.columns(min(len(CHANNELS), 6))
    for i, ch in enumerate(CHANNELS):
        cols[i % len(cols)].metric(ch, counts.get(ch, 0))
    st.caption(f"{total_active} active ideas across channels")

    st.divider()

    with (
        st.expander("➕ New idea", expanded=total_active == 0),
        st.form("add_idea", clear_on_submit=True),
    ):
        new_title = st.text_input("Title", max_chars=200, key="new_idea_title")
        new_hook = st.text_input(
            "Hook (one line)", max_chars=280, key="new_idea_hook",
            placeholder="The angle / why it's interesting",
        )
        cc1, cc2 = st.columns(2)
        new_channel = cc1.selectbox(
            "Channel", options=CHANNELS, index=0, key="new_idea_channel",
        )
        new_tags_raw = cc2.text_input(
            "Tags (comma-separated)", key="new_idea_tags",
            placeholder="claude, e-commerce, freelance",
        )
        new_notes = st.text_area("Notes", height=80, key="new_idea_notes")
        submitted = st.form_submit_button("Add idea")
        if submitted and new_title.strip():
            ideas_lib.add_idea(
                _store(),
                title=new_title,
                hook=new_hook or None,
                channel=new_channel,
                tags=[t.strip() for t in new_tags_raw.split(",") if t.strip()],
                notes=new_notes or None,
            )
            st.cache_data.clear()
            st.toast("Idea added", icon="💡")
            st.rerun()

    st.divider()

    filter_channel = None if channel_choice == "(all)" else channel_choice
    rows = _cached_ideas(channel=filter_channel, include_archived=include_archived)
    if not rows:
        st.info(
            "No ideas yet. Use the form above, or add from the CLI: "
            "`career-os ideas add --title \"…\"` (coming soon)."
        )
        return

    for idea in rows:
        _render_idea_row(idea)


def _render_idea_row(idea) -> None:
    # Distinct icon for project ideas to make the brainstorm flow discoverable.
    if idea.archived:
        border = "🗄️ "
    elif idea.channel == "project":
        border = "🚧 "
    else:
        border = "💡 "
    with st.container(border=True):
        cols = st.columns([0.7, 0.3])
        with cols[0]:
            st.markdown(f"**{border}{idea.title}**  ·  `{idea.channel}`")
            if idea.hook:
                st.markdown(f"_{idea.hook}_")
            if idea.tags:
                st.caption(" ".join(f"`{t}`" for t in idea.tags))
            if idea.notes:
                st.caption(idea.notes)
            st.caption(f"updated {idea.updated_at.date().isoformat()}")
        with cols[1]:
            if (
                idea.channel == "project"
                and not idea.archived
                and st.button(
                    "💡 Brainstorm with Claude",
                    key=f"brain_{idea.id}", use_container_width=True,
                    type="primary",
                    help="Spawns a new terminal running `claude` in a "
                         "workdir seeded with this idea + the brainstorm prompt.",
                )
            ):
                result = spawn_brainstorm_session(idea)
                if result.ok:
                    st.success(
                        f"Brainstorm terminal launched. Workdir: "
                        f"`{result.workdir}` — when Claude has edited "
                        "IDEA.md, click **Pull updates** below."
                    )
                else:
                    st.warning(result.fallback_message or "Spawn failed.")
            with st.popover("Edit", use_container_width=True):
                _render_edit_form(idea)
            if not idea.archived:
                if st.button(
                    "Archive", key=f"arch_{idea.id}", use_container_width=True,
                ):
                    ideas_lib.archive(_store(), idea.id, archived=True)
                    st.cache_data.clear()
                    st.rerun()
            else:
                if st.button(
                    "Unarchive", key=f"unarch_{idea.id}", use_container_width=True,
                ):
                    ideas_lib.archive(_store(), idea.id, archived=False)
                    st.cache_data.clear()
                    st.rerun()

        # Prior brainstorm sessions surface for project-channel ideas only.
        if idea.channel == "project":
            sessions = list_brainstorm_sessions(idea.id)
            if sessions:
                with st.expander(f"Brainstorm sessions ({len(sessions)})", expanded=False):
                    for sess in sessions[:8]:
                        scols = st.columns([0.6, 0.4])
                        scols[0].code(str(sess), language="text")
                        if scols[1].button(
                            "Pull updates ← IDEA.md",
                            key=f"pull_idea_{idea.id}_{sess.name}",
                            use_container_width=True,
                        ):
                            body = read_idea_body(sess)
                            if body is None:
                                st.error("IDEA.md is missing or unreadable.")
                            else:
                                # Brainstormed content lands in the notes field —
                                # largest free-text we have on Idea.
                                ideas_lib.update_idea(
                                    _store(), idea.id, notes=body,
                                )
                                st.cache_data.clear()
                                st.toast(f"Pulled from {sess.name}", icon="📥")
                                st.rerun()


def _render_edit_form(idea) -> None:
    with st.form(f"edit_idea_{idea.id}", clear_on_submit=False):
        title = st.text_input("Title", value=idea.title, max_chars=200)
        hook = st.text_input("Hook", value=idea.hook or "", max_chars=280)
        channel = st.selectbox(
            "Channel", options=CHANNELS,
            index=CHANNELS.index(idea.channel) if idea.channel in CHANNELS else 0,
        )
        tags_raw = st.text_input("Tags", value=", ".join(idea.tags))
        notes = st.text_area("Notes", value=idea.notes or "", height=100)
        save = st.form_submit_button("Save")
        if save:
            ideas_lib.update_idea(
                _store(), idea.id,
                title=title, hook=hook or None, channel=channel,
                tags=[t.strip() for t in tags_raw.split(",") if t.strip()],
                notes=notes or None,
            )
            st.cache_data.clear()
            st.toast("Saved", icon="💾")
            st.rerun()
    if st.button(
        "🗑 Delete (irreversible)", key=f"del_{idea.id}", use_container_width=True,
    ):
        ideas_lib.delete_idea(_store(), idea.id)
        st.cache_data.clear()
        st.rerun()
