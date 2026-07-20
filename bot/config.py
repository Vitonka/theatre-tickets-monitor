"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _parse_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                pass
    return frozenset(ids)


@dataclass(frozen=True)
class Config:
    telegram_token: str
    db_path: str = "data/monitors.db"
    poll_interval_min: int = 15
    # Optional whitelist. Empty => anyone who finds the bot may use it.
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    # Playwright knobs. executable_path lets you point at a system Chromium
    # (e.g. the pre-baked browser in some images); empty => Playwright default.
    browser_executable_path: str = ""
    headless: bool = True
    # Per-page render budget in milliseconds.
    page_timeout_ms: int = 45000

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather "
                "and put the token in your environment or .env file."
            )
        return cls(
            telegram_token=token,
            db_path=os.environ.get("DB_PATH", "data/monitors.db").strip(),
            poll_interval_min=int(os.environ.get("POLL_INTERVAL_MIN", "15")),
            allowed_user_ids=_parse_ids(os.environ.get("ALLOWED_USER_IDS", "")),
            browser_executable_path=os.environ.get(
                "BROWSER_EXECUTABLE_PATH", ""
            ).strip(),
            headless=os.environ.get("HEADLESS", "true").lower() != "false",
            page_timeout_ms=int(os.environ.get("PAGE_TIMEOUT_MS", "45000")),
        )
