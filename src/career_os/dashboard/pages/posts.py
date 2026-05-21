"""Posts page — drafts being shaped toward publish.

Independent from Ideas (no promote-flow). Each post has its own row, and the
"Improve with Claude" button spawns a new terminal running `claude` in a
workdir containing the current draft + the improve_post.md prompt.
"""
from __future__ import annotations

import streamlit as st

from career_os.config import Settings
from career_os.dashboard import posts as posts_lib
from career_os.dashboard.posts import CHANNELS, STATUSES
from career_os.db import Store
from career_os.post_studio import (
    CHANNEL_TARGETS as IDEA_CHANNEL_TARGETS,
)
from career_os.post_studio import (
    CHANNELS as IDEA_CHANNELS,
)
from career_os.post_studio import (
    IdeaInput,
    extract_urls,
    generate_from_idea,
)
from career_os.presence import (
    list_sessions,
    read_post_body,
    spawn_improve_session,
)
from career_os.profile import DEFAULT_PROFILE


def _store() -> Store:
    return Store(Settings.load().database_url)


@st.cache_data(ttl=60)
def _cached_posts(status: str | None, channel: str | None) -> list:
    return posts_lib.list_posts(_store(), status=status, channel=channel)


@st.cache_data(ttl=60)
def _cached_counts() -> dict[str, int]:
    return posts_lib.counts_by_status(_store())


def render() -> None:
    st.title("Posts")
    st.caption(
        "Drafts being shaped toward publish. Use **Improve with Claude** to "
        "spawn a terminal session that edits the draft interactively."
    )

    with st.sidebar:
        st.header("Filters")
        status_choice = st.selectbox(
            "Status", options=["(all)", *STATUSES], index=0, key="posts_status_filter",
        )
        channel_choice = st.selectbox(
            "Channel", options=["(all)", *CHANNELS], index=0, key="posts_channel_filter",
        )
        st.divider()
        if st.button("🔄 Refresh", use_container_width=True, key="posts_refresh"):
            st.cache_data.clear()
            st.rerun()

    counts = _cached_counts()
    c1, c2, c3 = st.columns(3)
    c1.metric("Drafting", counts.get("drafting", 0))
    c2.metric("Ready", counts.get("ready", 0))
    c3.metric("Posted", counts.get("posted", 0))

    st.divider()

    settings = Settings.load()
    has_api_key = bool(settings.anthropic_api_key)

    with st.expander(
        "💡 Draft from idea / links",
        expanded=sum(counts.values()) == 0,
    ):
        _render_idea_generator(has_api_key, settings.anthropic_api_key)

    with (
        st.expander("➕ New post (blank)", expanded=False),
        st.form("add_post", clear_on_submit=True),
    ):
        new_title = st.text_input("Title", max_chars=200, key="new_post_title")
        cc1, cc2 = st.columns(2)
        new_channel = cc1.selectbox(
            "Channel", options=CHANNELS, index=0, key="new_post_channel",
        )
        new_body = st.text_area(
            "Body (Markdown)", height=200, key="new_post_body",
            placeholder="# Title\n\nFirst paragraph...",
        )
        new_notes = st.text_input("Notes", key="new_post_notes")
        submitted = st.form_submit_button("Create draft")
        if submitted and new_title.strip():
            posts_lib.add_post(
                _store(),
                title=new_title, channel=new_channel,
                body=new_body, notes=new_notes or None,
            )
            st.cache_data.clear()
            st.toast("Draft created", icon="📝")
            st.rerun()

    st.divider()

    filter_status = None if status_choice == "(all)" else status_choice
    filter_channel = None if channel_choice == "(all)" else channel_choice
    rows = _cached_posts(status=filter_status, channel=filter_channel)
    if not rows:
        st.info("No posts yet. Use the form above to create one.")
        return

    for post in rows:
        _render_post(post)


def _render_post(post) -> None:
    status_icon = {"drafting": "✏️", "ready": "🟢", "posted": "📤"}.get(post.status, "•")
    with st.container(border=True):
        head_cols = st.columns([0.6, 0.4])
        with head_cols[0]:
            st.markdown(
                f"### {status_icon} {post.title}\n"
                f"`{post.channel}`  ·  status: `{post.status}`  ·  "
                f"updated {post.updated_at.date().isoformat()}"
            )
        with head_cols[1]:
            _render_action_buttons(post)

        with st.expander("Body + edit", expanded=False):
            _render_body_editor(post)

        sessions = list_sessions(post.id)
        if sessions:
            with st.expander(f"Improve sessions ({len(sessions)})", expanded=False):
                for sess in sessions[:8]:
                    cols = st.columns([0.6, 0.4])
                    cols[0].code(str(sess), language="text")
                    if cols[1].button(
                        "Pull updates ← POST.md", key=f"pull_{post.id}_{sess.name}",
                    ):
                        body = read_post_body(sess)
                        if body is None:
                            st.error("POST.md is missing or unreadable.")
                        else:
                            posts_lib.update_post(_store(), post.id, body=body)
                            st.cache_data.clear()
                            st.toast(f"Pulled from {sess.name}", icon="📥")
                            st.rerun()


def _render_action_buttons(post) -> None:
    cols = st.columns(2)
    if cols[0].button(
        "✨ Improve with Claude", key=f"improve_{post.id}", use_container_width=True,
        help="Spawns a new terminal running `claude` in a workdir with this draft.",
    ):
        result = spawn_improve_session(post)
        if result.ok:
            st.success(
                f"Terminal launched. Workdir: `{result.workdir}` — when Claude has "
                "edited POST.md, click **Pull updates** under Improve sessions."
            )
        else:
            st.warning(result.fallback_message or "Spawn failed.")

    next_status = _next_status(post.status)
    if next_status and cols[1].button(
        f"→ {next_status}", key=f"adv_{post.id}", use_container_width=True,
    ):
        posts_lib.set_status(_store(), post.id, next_status)
        st.cache_data.clear()
        st.rerun()


def _render_body_editor(post) -> None:
    new_body = st.text_area(
        "Body", value=post.body, height=320, key=f"body_{post.id}",
        label_visibility="collapsed",
    )
    new_notes = st.text_input("Notes", value=post.notes or "", key=f"notes_{post.id}")
    cols = st.columns([0.3, 0.3, 0.4])
    if cols[0].button("💾 Save edits", key=f"save_{post.id}", use_container_width=True):
        posts_lib.update_post(
            _store(), post.id, body=new_body, notes=new_notes or None,
        )
        st.cache_data.clear()
        st.toast("Saved", icon="💾")
        st.rerun()
    with cols[1].popover("🗑 Delete", use_container_width=True):
        st.write(
            "This permanently deletes the post and its body. "
            "Improve-session workdirs on disk are kept."
        )
        if st.button("Confirm delete", key=f"confirm_del_{post.id}", type="primary"):
            posts_lib.delete_post(_store(), post.id)
            st.cache_data.clear()
            st.rerun()


def _render_idea_generator(has_api_key: bool, api_key: str | None) -> None:
    st.caption(
        "Paste an idea, angle, or rough thought. URLs in the text become "
        "references for the model. One draft is created per selected channel."
    )
    if not has_api_key:
        st.info(
            "ANTHROPIC_API_KEY not set — generator uses the dry-run template "
            "(still creates editable drafts).",
            icon="ℹ️",
        )

    idea_text = st.text_area(
        "Idea / angle / notes",
        height=160,
        key="idea_gen_text",
        placeholder=(
            "e.g. The thing nobody tells you about running Claude SDK "
            "in production is the cost of streaming retries. "
            "https://docs.anthropic.com/..."
        ),
    )
    extra_urls_text = st.text_input(
        "Extra reference URLs (space- or comma-separated, optional)",
        key="idea_gen_urls",
        placeholder="https://news.ycombinator.com/item?id=...  https://...",
    )
    cc1, cc2 = st.columns(2)
    angle = cc1.text_input(
        "Angle (optional)",
        key="idea_gen_angle",
        placeholder="contrarian / production-reality / postmortem",
    )
    audience = cc2.text_input(
        "Audience (optional)",
        key="idea_gen_audience",
        placeholder="senior backend engineers shipping LLM features",
    )

    target_channels = st.multiselect(
        "Channels to generate",
        options=list(IDEA_CHANNELS),
        default=list(IDEA_CHANNELS),
        format_func=lambda c: f"{c} ({IDEA_CHANNEL_TARGETS[c]})",
        key="idea_gen_channels",
    )

    cols = st.columns([0.3, 0.7])
    if cols[0].button(
        "✨ Generate drafts",
        type="primary", use_container_width=True,
        key="idea_gen_submit",
        disabled=not (idea_text.strip() and target_channels),
    ):
        urls = extract_urls(idea_text) + extract_urls(extra_urls_text)
        deduped: list[str] = []
        for u in urls:
            if u not in deduped:
                deduped.append(u)
        idea = IdeaInput(
            idea=idea_text.strip(),
            urls=deduped,
            angle=angle.strip() or None,
            audience=audience.strip() or None,
        )
        created: list[str] = []
        no_fits: list[str] = []
        with st.spinner(
            f"Drafting {len(target_channels)} post(s) via Claude..."
        ):
            for channel in target_channels:
                result = generate_from_idea(
                    api_key=api_key, idea=idea, channel=channel,
                    profile=DEFAULT_PROFILE,
                    dry_run=not api_key,
                )
                if result.is_no_fit:
                    no_fits.append(
                        f"{channel}: {result.no_fit_reason or '—'}"
                    )
                    continue
                title = _derive_idea_title(idea, channel)
                posts_lib.add_post(
                    _store(), title=title, channel=channel,
                    body=result.body,
                    notes=(
                        f"Generated from idea · model={result.model}"
                        + (f" · refs={len(deduped)}" if deduped else "")
                    ),
                )
                created.append(channel)
        st.cache_data.clear()
        if created:
            st.success(
                f"Created {len(created)} draft(s): {', '.join(created)}",
                icon="✨",
            )
        for fit in no_fits:
            st.warning(f"Claude declined: {fit}", icon="🛑")
        if created:
            st.rerun()


def _derive_idea_title(idea: IdeaInput, channel: str) -> str:
    first_line = idea.idea.strip().splitlines()[0]
    prefix = {"x": "🐦", "linkedin": "💼", "blog": "📰"}.get(channel, channel)
    return f"{prefix} {first_line}"[:200]


def _next_status(current: str) -> str | None:
    order = list(STATUSES)
    try:
        i = order.index(current)
    except ValueError:
        return None
    if i + 1 >= len(order):
        return None
    return order[i + 1]
