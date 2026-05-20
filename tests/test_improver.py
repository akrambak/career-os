from __future__ import annotations

from pathlib import Path

import pytest

from career_os.dashboard import posts as posts_lib
from career_os.dashboard.network import Environment
from career_os.db import Store
from career_os.presence import improver


@pytest.fixture
def store(tmp_path):
    return Store(f"sqlite:///{tmp_path / 'imp.db'}")


def _make_post(store: Store) -> object:
    return posts_lib.add_post(
        store, title="Test post", channel="linkedin",
        body="Original body, version 1.\n",
    )


def test_prepare_session_writes_three_files(store, tmp_path, monkeypatch):
    monkeypatch.setattr(improver, "SESSIONS_ROOT", tmp_path / "sessions")
    post = _make_post(store)
    workdir = improver.prepare_session(post, root=tmp_path / "sessions")
    assert workdir.exists()
    assert (workdir / "POST.md").exists()
    assert (workdir / "ORIGINAL.md").exists()
    assert (workdir / "CLAUDE.md").exists()
    post_md = (workdir / "POST.md").read_text()
    assert "Original body, version 1" in post_md
    assert "channel: linkedin" in post_md  # frontmatter
    claude_md = (workdir / "CLAUDE.md").read_text()
    assert "linkedin" in claude_md.lower()


def test_prepare_session_empty_body_gets_placeholder(store, tmp_path):
    post = posts_lib.add_post(store, title="Empty draft", body="")
    workdir = improver.prepare_session(post, root=tmp_path)
    body = (workdir / "POST.md").read_text()
    assert "empty draft" in body.lower() or "write the first paragraph" in body


def test_read_post_body_strips_frontmatter(tmp_path):
    workdir = tmp_path / "session"
    workdir.mkdir()
    (workdir / "POST.md").write_text(
        "---\nid: 1\ntitle: x\n---\n\nThe real body.\nLine two.\n"
    )
    body = improver.read_post_body(workdir)
    assert body == "The real body.\nLine two.\n"


def test_read_post_body_missing(tmp_path):
    assert improver.read_post_body(tmp_path / "nope") is None


def test_build_spawn_command_wsl_prefers_wt(monkeypatch, tmp_path):
    monkeypatch.setattr(
        improver, "_find_executable",
        lambda name: "/mnt/c/Windows/System32/wt.exe" if name == "wt.exe" else None,
    )
    env = Environment(is_wsl=True, is_docker=False, primary_ip=None, hostname="x")
    cmd = improver.build_spawn_command(tmp_path / "work", env, initial_message="hello")
    assert cmd is not None
    assert cmd[0] == "cmd.exe"
    assert "wt.exe" in cmd
    assert any("claude 'hello'" in part for part in cmd)
    assert any(str(tmp_path / "work") in part for part in cmd)


def test_build_spawn_command_wsl_no_wt_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(
        improver, "_find_executable",
        lambda name: "/mnt/c/Windows/System32/cmd.exe" if name == "cmd.exe" else None,
    )
    env = Environment(is_wsl=True, is_docker=False, primary_ip=None, hostname="x")
    cmd = improver.build_spawn_command(tmp_path / "w", env)
    assert cmd is not None
    assert "wsl.exe" in cmd
    assert "wt.exe" not in cmd


def test_build_spawn_command_wsl_no_terminal_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(improver, "_find_executable", lambda name: None)
    env = Environment(is_wsl=True, is_docker=False, primary_ip=None, hostname="x")
    assert improver.build_spawn_command(tmp_path / "w", env) is None


def test_build_spawn_command_linux_picks_first_available(monkeypatch, tmp_path):
    monkeypatch.setattr(
        improver, "_find_executable",
        lambda name: "/usr/bin/" + name if name == "gnome-terminal" else None,
    )
    env = Environment(is_wsl=False, is_docker=False, primary_ip=None, hostname="x")
    cmd = improver.build_spawn_command(tmp_path / "w", env)
    assert cmd is not None
    assert cmd[0] == "gnome-terminal"
    assert any(str(tmp_path / "w") in part for part in cmd)


def test_build_spawn_command_linux_falls_through(monkeypatch, tmp_path):
    monkeypatch.setattr(
        improver, "_find_executable",
        lambda name: "/usr/bin/xterm" if name == "xterm" else None,
    )
    env = Environment(is_wsl=False, is_docker=False, primary_ip=None, hostname="x")
    cmd = improver.build_spawn_command(tmp_path / "w", env)
    assert cmd is not None
    assert cmd[0] == "xterm"


def test_list_sessions_orders_newest_first(tmp_path):
    root = tmp_path
    (root / "post-1-20260101-0900").mkdir()
    (root / "post-1-20260102-1000").mkdir()
    (root / "post-2-20260101-0900").mkdir()  # different post — should be excluded
    sessions = improver.list_sessions(1, root=root)
    assert [s.name for s in sessions] == [
        "post-1-20260102-1000", "post-1-20260101-0900",
    ]


def test_shell_quote_escapes_single_quotes():
    assert improver._shell_quote("hello world") == "'hello world'"
    # An embedded single quote must close, escape, reopen.
    quoted = improver._shell_quote("it's a draft")
    # Bash will read 'it'\''s a draft' as it's a draft
    assert quoted == "'it'\\''s a draft'"


def test_spawn_falls_back_when_no_terminal(monkeypatch, store, tmp_path):
    monkeypatch.setattr(improver, "_find_executable", lambda name: None)
    monkeypatch.setattr(improver, "SESSIONS_ROOT", tmp_path / "sessions")
    env = Environment(is_wsl=False, is_docker=False, primary_ip=None, hostname="x")
    post = _make_post(store)
    result = improver.spawn_improve_session(post, env=env)
    assert result.ok is False
    assert "claude" in (result.fallback_message or "")
    assert result.workdir.exists()


def test_prompt_path_exists():
    """The prompt file the improver renders into CLAUDE.md must be on disk."""
    assert improver.PROMPT_PATH.exists(), (
        f"{improver.PROMPT_PATH} missing — see Posts page Improve flow"
    )


def test_spawn_command_does_not_contain_unsubstituted_placeholders(tmp_path):
    """Belt-and-suspenders: no '<...>' placeholders should leak into argv."""
    env = Environment(is_wsl=False, is_docker=False, primary_ip=None, hostname="x")
    # Force xterm so we get a deterministic argv shape.
    from unittest.mock import patch

    with patch.object(
        improver, "_find_executable",
        side_effect=lambda name: "/usr/bin/xterm" if name == "xterm" else None,
    ):
        cmd = improver.build_spawn_command(Path("/tmp/work"), env)
    assert cmd is not None
    joined = " ".join(cmd)
    assert "<" not in joined and ">" not in joined
