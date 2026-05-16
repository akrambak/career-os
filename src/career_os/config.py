from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    database_url: str
    smtp_provider: str | None
    smtp_api_key: str | None
    smtp_from: str
    smtp_to: str

    @classmethod
    def load(cls) -> Settings:
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or None,
            database_url=os.getenv(
                "DATABASE_URL",
                f"sqlite:///{REPO_ROOT / 'data' / 'career_os.db'}",
            ),
            smtp_provider=os.getenv("SMTP_PROVIDER") or None,
            smtp_api_key=os.getenv("SMTP_API_KEY") or None,
            smtp_from=os.getenv("SMTP_FROM", "me@bak-dev.com"),
            smtp_to=os.getenv("SMTP_TO", "me@bak-dev.com"),
        )
