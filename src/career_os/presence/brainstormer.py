"""Spawn a `claude` terminal session against a project-channel Idea.

Mirrors the improve-post flow (see `improver.py`) but anchored on
`dashboard.ideas.Idea` instead of `dashboard.posts.Post`, with the
brainstorm_project.md prompt. The shell-spawn primitive
(`build_spawn_command`) is shared from `improver.py` — same WSL2/Linux
detection logic, just a different workdir + prompt.

Workflow:
  1. `prepare_brainstorm_session(idea)` writes IDEA.md / ORIGINAL.md /
     CLAUDE.md into `data/brainstorm-sessions/idea-<id>-<ts>/`.
  2. `spawn_brainstorm_session(idea)` opens a new terminal running
     `claude '<initial msg>'` in that workdir.
  3. After Claude edits IDEA.md, the dashboard's "Pull updates" button
     calls `read_idea_body(workdir)` and writes the updated body back
     onto the idea's `notes` field (the largest free-text we have).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..dashboard.ideas import Idea
from ..dashboard.network import Environment, detect_environment
from .improver import build_spawn_command  # shared shell-spawn primitive

PROMPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "presence" / "prompts" / "brainstorm_project.md"
)
SESSIONS_ROOT = (
    Path(__file__).resolve().parents[3] / "data" / "brainstorm-sessions"
)

INITIAL_USER_MESSAGE = (
    "Read IDEA.md and CLAUDE.md. Push back on the weakest assumption "
    "in this idea — pick ONE section (Problem, Why now, Smallest "
    "shippable, Edge, Killer questions, Compounding return) and ask "
    "the sharpest question. Wait for my answer before moving on."
)


@dataclass(frozen=True)
class BrainstormResult:
    ok: bool
    workdir: Path
    command: list[str]
    fallback_message: str | None


def prepare_brainstorm_session(idea: Idea, root: Path | None = None) -> Path:
    """Create the per-idea brainstorm workdir + write IDEA.md / ORIGINAL.md
    / CLAUDE.md."""
    base = root or SESSIONS_ROOT
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    workdir = base / f"idea-{idea.id}-{stamp}"
    workdir.mkdir(parents=True, exist_ok=True)

    frontmatter = (
        "---\n"
        f"id: {idea.id}\n"
        f"title: {idea.title}\n"
        f"channel: {idea.channel}\n"
        f"tags: {', '.join(idea.tags) if idea.tags else ''}\n"
        "---\n\n"
    )
    body = _render_idea_body(idea)
    (workdir / "IDEA.md").write_text(frontmatter + body, encoding="utf-8")
    (workdir / "ORIGINAL.md").write_text(frontmatter + body, encoding="utf-8")
    (workdir / "CLAUDE.md").write_text(_render_claude_md(idea), encoding="utf-8")
    return workdir


def _render_idea_body(idea: Idea) -> str:
    """Initial IDEA.md body — pull whatever the user has captured in the
    Ideas page (title + hook + notes) and lay it out under the sections
    the brainstorm prompt expects."""
    parts: list[str] = [f"# {idea.title}\n"]
    if idea.hook:
        parts.append(f"**Hook:** {idea.hook}\n")
    if idea.tags:
        parts.append(f"**Tags:** {', '.join(idea.tags)}\n")
    parts.append("")
    parts.append("## Problem")
    parts.append("(who has this pain? be specific)\n")
    parts.append("## Why now")
    parts.append("(what just changed that makes this newly possible/urgent?)\n")
    parts.append("## Smallest shippable version")
    parts.append("(one sentence — what can ship in 2 weekends?)\n")
    parts.append("## Why this user")
    parts.append("(what's Akram's edge here?)\n")
    parts.append("## Killer questions")
    parts.append("(three questions whose answers would kill this)\n")
    parts.append("## Compounding return")
    parts.append("(if this ships, what asset is gained?)\n")
    parts.append("## Next 3 concrete actions")
    parts.append("(numbered, each <2h)\n")
    if idea.notes:
        parts.append("---\n\n## Notes (carried over from Ideas page)\n")
        parts.append(idea.notes)
    return "\n".join(parts)


def _render_claude_md(idea: Idea) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""
    header = (
        f"# Brainstorm IDEA.md — {idea.title}\n\n"
        f"Channel: **{idea.channel}**  ·  "
        f"Tags: {', '.join(idea.tags) if idea.tags else '(none)'}\n\n"
        "The current state of the idea is in `IDEA.md`. The unchanged "
        "starting version is in `ORIGINAL.md` for reference — don't "
        "edit ORIGINAL.md.\n\n---\n\n"
    )
    return header + template


def spawn_brainstorm_session(
    idea: Idea, env: Environment | None = None,
) -> BrainstormResult:
    """End-to-end: prepare workdir, spawn terminal, return result."""
    workdir = prepare_brainstorm_session(idea)
    detected = env or detect_environment()
    command = build_spawn_command(workdir, detected, INITIAL_USER_MESSAGE)
    if command is None:
        return BrainstormResult(
            ok=False, workdir=workdir, command=[],
            fallback_message=(
                "Could not auto-spawn a terminal — open one yourself and run:\n"
                f"    cd {workdir}\n"
                "    claude"
            ),
        )
    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return BrainstormResult(
            ok=True, workdir=workdir, command=command, fallback_message=None,
        )
    except (OSError, ValueError) as exc:
        return BrainstormResult(
            ok=False, workdir=workdir, command=command,
            fallback_message=(
                f"Spawn failed ({type(exc).__name__}: {exc}). Run manually:\n"
                f"    cd {workdir}\n"
                "    claude"
            ),
        )


def read_idea_body(workdir: Path) -> str | None:
    """Pull the (possibly Claude-edited) body back out of IDEA.md.

    Strips the YAML frontmatter we wrote in `prepare_brainstorm_session`.
    Returns None if IDEA.md is missing or unreadable.
    """
    path = workdir / "IDEA.md"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + len("\n---\n"):].lstrip("\n")
    return text


def list_sessions(idea_id: int, root: Path | None = None) -> list[Path]:
    """All workdirs ever created for a given idea, newest first."""
    base = root or SESSIONS_ROOT
    if not base.exists():
        return []
    prefix = f"idea-{idea_id}-"
    return sorted(
        (p for p in base.iterdir() if p.is_dir() and p.name.startswith(prefix)),
        reverse=True,
    )


__all__ = [
    "BrainstormResult", "PROMPT_PATH", "INITIAL_USER_MESSAGE",
    "prepare_brainstorm_session", "spawn_brainstorm_session",
    "read_idea_body", "list_sessions",
]
