from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .salary import Compensation


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Channel(StrEnum):
    FT = "ft"
    FREELANCE = "freelance"
    EITHER = "either"


class JobPost(BaseModel):
    """A single posting from any source.

    `compensation` is the source's free-text salary string (preserved for
    display). `parsed_compensation` is the structured form (see
    `career_os.salary.Compensation`) — set by scrapers at ingest time and
    by `_row_to_job` when reading from the DB. None means we couldn't
    extract structure; the raw string is still in `compensation`.
    """
    # Compensation is a frozen dataclass, not a pydantic model — allow it as a
    # field by skipping pydantic's arbitrary-type guard.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str = Field(description="scraper key, e.g. 'remoteok'")
    external_id: str = Field(description="stable id from the source")
    url: HttpUrl
    title: str
    company: str | None = None
    location: str | None = None
    description: str
    tags: list[str] = Field(default_factory=list)
    channel: Channel = Channel.EITHER
    compensation: str | None = None
    parsed_compensation: Compensation | None = None
    posted_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=_utc_now)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.external_id}"


class Score(BaseModel):
    job_key: str
    fit: int = Field(ge=0, le=100)
    reasoning: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    suggested_angle: str | None = None
    scored_at: datetime = Field(default_factory=_utc_now)


class Profile(BaseModel):
    """The user's profile, fed to the scorer."""

    name: str = "Bakhouche Akram"
    handle: str = "AkBak"
    headline: str
    years_experience: int
    proven_stack: list[str]
    new_stack: list[str]
    target_channels: list[Channel]
    deal_breakers: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
