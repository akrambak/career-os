"""Presence module — content prep + cross-posting helpers."""
from .brainstormer import (
    BrainstormResult,
    prepare_brainstorm_session,
    read_idea_body,
    spawn_brainstorm_session,
)
from .brainstormer import list_sessions as list_brainstorm_sessions
from .improver import (
    SpawnResult,
    build_spawn_command,
    list_sessions,
    prepare_session,
    read_post_body,
    spawn_improve_session,
)

__all__ = [
    # improve-post (per draft on the Posts page)
    "SpawnResult", "build_spawn_command",
    "list_sessions", "prepare_session",
    "read_post_body", "spawn_improve_session",
    # brainstorm-idea (per project-channel idea on the Ideas page)
    "BrainstormResult",
    "prepare_brainstorm_session", "spawn_brainstorm_session",
    "read_idea_body", "list_brainstorm_sessions",
]
