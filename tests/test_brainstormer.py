"""Brainstormer terminal-spawn tests (project-idea HITL flow).

Mirrors test_improver.py — same shell-spawn primitive, different
workdir + prompt.
"""
from __future__ import annotations

import pytest

from career_os.dashboard import ideas as ideas_lib
from career_os.dashboard.network import Environment
from career_os.db import Store
from career_os.presence import brainstormer


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'b.db'}")


def _make_idea(store: Store) -> object:
    return ideas_lib.add_idea(
        store, title="OSS Claude SDK starter for Laravel",
        hook="One-command bootstrap for AI-agent Laravel apps",
        channel="project", tags=["laravel", "claude"],
        notes="Free-form notes the user typed in the Ideas page.",
    )


def test_prepare_session_writes_three_files(store, tmp_path, monkeypatch):
    monkeypatch.setattr(brainstormer, "SESSIONS_ROOT", tmp_path / "sessions")
    idea = _make_idea(store)
    workdir = brainstormer.prepare_brainstorm_session(
        idea, root=tmp_path / "sessions",
    )
    assert workdir.exists()
    assert (workdir / "IDEA.md").exists()
    assert (workdir / "ORIGINAL.md").exists()
    assert (workdir / "CLAUDE.md").exists()
    idea_md = (workdir / "IDEA.md").read_text()
    assert "channel: project" in idea_md          # frontmatter
    assert "OSS Claude SDK starter" in idea_md    # title
    assert "## Problem" in idea_md                # section scaffolding
    assert "## Killer questions" in idea_md
    claude_md = (workdir / "CLAUDE.md").read_text()
    assert "project" in claude_md.lower()


def test_prepare_session_carries_existing_notes(store, tmp_path):
    idea = _make_idea(store)
    workdir = brainstormer.prepare_brainstorm_session(idea, root=tmp_path)
    body = (workdir / "IDEA.md").read_text()
    assert "Free-form notes the user typed" in body


def test_read_idea_body_strips_frontmatter(tmp_path):
    workdir = tmp_path / "session"
    workdir.mkdir()
    (workdir / "IDEA.md").write_text(
        "---\nid: 1\ntitle: x\n---\n\nThe real body.\nLine two.\n"
    )
    body = brainstormer.read_idea_body(workdir)
    assert body == "The real body.\nLine two.\n"


def test_read_idea_body_missing(tmp_path):
    assert brainstormer.read_idea_body(tmp_path / "nope") is None


def test_list_sessions_orders_newest_first(tmp_path):
    root = tmp_path
    (root / "idea-1-20260520-0900").mkdir()
    (root / "idea-1-20260520-1000").mkdir()
    (root / "idea-2-20260520-0900").mkdir()  # different idea — excluded
    sessions = brainstormer.list_sessions(1, root=root)
    assert [s.name for s in sessions] == [
        "idea-1-20260520-1000", "idea-1-20260520-0900",
    ]


def test_spawn_falls_back_when_no_terminal(monkeypatch, store, tmp_path):
    from career_os.presence import improver
    monkeypatch.setattr(improver, "_find_executable", lambda name: None)
    monkeypatch.setattr(brainstormer, "SESSIONS_ROOT", tmp_path / "sessions")
    env = Environment(is_wsl=False, is_docker=False, primary_ip=None, hostname="x")
    idea = _make_idea(store)
    result = brainstormer.spawn_brainstorm_session(idea, env=env)
    assert result.ok is False
    assert "claude" in (result.fallback_message or "")
    assert result.workdir.exists()


def test_brainstorm_prompt_path_exists():
    """The brainstorm prompt file must be on disk."""
    assert brainstormer.PROMPT_PATH.exists(), (
        f"{brainstormer.PROMPT_PATH} missing"
    )


def test_brainstormer_reexported_from_presence():
    """Sanity: the dashboard imports these via career_os.presence."""
    from career_os import presence
    assert hasattr(presence, "spawn_brainstorm_session")
    assert hasattr(presence, "prepare_brainstorm_session")
    assert hasattr(presence, "read_idea_body")
    assert hasattr(presence, "list_brainstorm_sessions")
    assert hasattr(presence, "BrainstormResult")
