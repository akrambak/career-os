"""Presence module — content prep + cross-posting helpers."""
from .improver import (
    SpawnResult,
    build_spawn_command,
    list_sessions,
    prepare_session,
    read_post_body,
    spawn_improve_session,
)

__all__ = [
    "SpawnResult", "build_spawn_command",
    "list_sessions", "prepare_session",
    "read_post_body", "spawn_improve_session",
]
