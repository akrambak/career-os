"""Spawn a new terminal running `claude` interactively against a post draft.

The dashboard "Improve with Claude" button calls `spawn_improve_session(post)`.
That:

  1. Writes a workdir under `data/improve-sessions/<post-id>-<ts>/` containing
     POST.md (current draft), ORIGINAL.md (frozen reference), CLAUDE.md
     (system instructions derived from presence/prompts/improve_post.md).
  2. Detects the host environment (WSL2 vs native Linux).
  3. Spawns a new terminal window running `claude` in that workdir, with
     an initial prompt that points Claude at POST.md.

The user chats with Claude in the new terminal, Claude edits POST.md, the
user pulls the updated body back into the dashboard via the "Pull updates"
button on the Posts page.

This module is pure-Python — no streamlit import. The terminal-spawn command
is built as a list of strings (`build_spawn_command`) so it can be unit-tested
without actually spawning anything.
"""
from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..dashboard.network import Environment, detect_environment
from ..dashboard.posts import Post

PROMPT_PATH = Path(__file__).resolve().parents[3] / "presence" / "prompts" / "improve_post.md"
SESSIONS_ROOT = Path(__file__).resolve().parents[3] / "data" / "improve-sessions"

INITIAL_USER_MESSAGE = (
    "Read POST.md and CLAUDE.md. Diagnose the single weakest part of the "
    "draft (lead, specifics, length-for-channel, or CTA) and propose ONE "
    "targeted rewrite of that section — show before/after side by side. "
    "Wait for me before touching the rest."
)


@dataclass(frozen=True)
class SpawnResult:
    ok: bool
    workdir: Path
    command: list[str]            # the command that was (or would be) spawned
    fallback_message: str | None  # set when spawn failed — instructions for the user


def prepare_session(post: Post, root: Path | None = None) -> Path:
    """Create the per-post workdir and write POST.md, ORIGINAL.md, CLAUDE.md.

    Returns the workdir path. Idempotent on (post.id, minute) — re-running
    within the same minute writes to the same dir; after that, a new dir.
    """
    base = root or SESSIONS_ROOT
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    workdir = base / f"post-{post.id}-{stamp}"
    workdir.mkdir(parents=True, exist_ok=True)

    frontmatter = (
        "---\n"
        f"id: {post.id}\n"
        f"title: {post.title}\n"
        f"channel: {post.channel}\n"
        f"status: {post.status}\n"
        "---\n\n"
    )
    body = post.body or "(empty draft — write the first paragraph here)\n"
    (workdir / "POST.md").write_text(frontmatter + body, encoding="utf-8")
    (workdir / "ORIGINAL.md").write_text(frontmatter + body, encoding="utf-8")
    (workdir / "CLAUDE.md").write_text(_render_claude_md(post), encoding="utf-8")
    return workdir


def _render_claude_md(post: Post) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8") if PROMPT_PATH.exists() else ""
    header = (
        f"# Improve POST.md — {post.title}\n\n"
        f"Channel: **{post.channel}**  ·  Status: **{post.status}**\n\n"
        "The draft is in `POST.md`. The unchanged starting version is in "
        "`ORIGINAL.md` for reference — don't edit ORIGINAL.md.\n\n"
        "---\n\n"
    )
    return header + template


def build_spawn_command(
    workdir: Path, env: Environment, initial_message: str = INITIAL_USER_MESSAGE,
) -> list[str] | None:
    """Pure: pick the right terminal-spawn invocation for the env.

    Returns None if no spawnable terminal could be found — caller falls
    back to printing the command for the user to run themselves.
    """
    quoted_workdir = _shell_quote(str(workdir))
    quoted_msg = _shell_quote(initial_message)
    bash_command = f"cd {quoted_workdir} && claude {quoted_msg}"

    if env.is_wsl:
        wt = _find_executable("wt.exe") or _find_executable("cmd.exe")
        if wt and wt.endswith("wt.exe"):
            # Windows Terminal: spawn via cmd.exe /c start so it detaches.
            return [
                "cmd.exe", "/c", "start", "",
                "wt.exe", "wsl.exe", "--", "bash", "-c", bash_command,
            ]
        if wt:  # only cmd.exe — fall back to plain cmd start of bash
            return [
                "cmd.exe", "/c", "start", "",
                "wsl.exe", "--", "bash", "-c", bash_command,
            ]
        return None

    # Native Linux: try common terminals in order of preference.
    for term, argv_builder in _LINUX_TERMINALS:
        if _find_executable(term):
            return argv_builder(workdir, bash_command)
    return None


def spawn_improve_session(
    post: Post, env: Environment | None = None,
) -> SpawnResult:
    """End-to-end: prepare workdir, spawn terminal, return SpawnResult."""
    workdir = prepare_session(post)
    detected = env or detect_environment()
    command = build_spawn_command(workdir, detected)
    if command is None:
        return SpawnResult(
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
        return SpawnResult(ok=True, workdir=workdir, command=command, fallback_message=None)
    except (OSError, ValueError) as exc:
        return SpawnResult(
            ok=False, workdir=workdir, command=command,
            fallback_message=(
                f"Spawn failed ({type(exc).__name__}: {exc}). Run manually:\n"
                f"    cd {workdir}\n"
                "    claude"
            ),
        )


def read_post_body(workdir: Path) -> str | None:
    """Pull the (possibly Claude-edited) body back out of POST.md.

    Strips the YAML frontmatter we wrote in `prepare_session`. Returns None
    if POST.md is gone or unreadable.
    """
    path = workdir / "POST.md"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    # Strip a leading ---\n...---\n\n frontmatter block if present.
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            text = text[end + len("\n---\n"):].lstrip("\n")
    return text


def list_sessions(post_id: int, root: Path | None = None) -> list[Path]:
    """All workdirs ever created for a given post, newest first."""
    base = root or SESSIONS_ROOT
    if not base.exists():
        return []
    prefix = f"post-{post_id}-"
    return sorted(
        (p for p in base.iterdir() if p.is_dir() and p.name.startswith(prefix)),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shell_quote(s: str) -> str:
    """Single-quote for bash. Escapes embedded single quotes."""
    return "'" + s.replace("'", "'\\''") + "'"


def _find_executable(name: str) -> str | None:
    return shutil.which(name)


def _gnome_terminal_argv(workdir: Path, bash_command: str) -> list[str]:
    return ["gnome-terminal", f"--working-directory={workdir}", "--", "bash", "-c",
            bash_command + "; exec bash"]


def _xterm_argv(workdir: Path, bash_command: str) -> list[str]:
    return ["x-terminal-emulator", "-e", f"bash -c {_shell_quote(bash_command)}"]


def _konsole_argv(workdir: Path, bash_command: str) -> list[str]:
    return ["konsole", "--workdir", str(workdir), "-e", "bash", "-c",
            bash_command + "; exec bash"]


def _xterm_basic_argv(workdir: Path, bash_command: str) -> list[str]:
    return ["xterm", "-e", "bash", "-c", bash_command + "; exec bash"]


_LINUX_TERMINALS: list[tuple[str, Callable[[Path, str], list[str]]]] = [
    ("gnome-terminal", _gnome_terminal_argv),
    ("konsole", _konsole_argv),
    ("x-terminal-emulator", _xterm_argv),
    ("xterm", _xterm_basic_argv),
]
