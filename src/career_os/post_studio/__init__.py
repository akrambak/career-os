"""Idea-driven post generator. Separate from the trends pipeline.

The user pastes a free-form idea + optional URLs; the generator drafts
one post per target channel (blog / linkedin / x) anchored in the user's
profile. Reuses the Claude SDK + tenacity + dry-run pattern from
career_os.trends.generator.
"""
from .generator import (
    CHANNEL_TARGETS,
    CHANNELS,
    GENERATOR_MODEL,
    NO_FIT_MARKER,
    GeneratedPost,
    IdeaInput,
    extract_urls,
    generate_from_idea,
)

__all__ = [
    "CHANNELS", "CHANNEL_TARGETS", "GENERATOR_MODEL", "NO_FIT_MARKER",
    "GeneratedPost", "IdeaInput",
    "generate_from_idea", "extract_urls",
]
