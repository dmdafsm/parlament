"""Runtime settings from environment variables (12-factor); defaults suit local development."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Legislature currently in office (elected 1 December 2024).
CURRENT_LEGISLATURE = 2024


@dataclass(frozen=True)
class Settings:
    database_url: str
    data_dir: Path
    request_delay: float
    fetch_mode: str  # "live", "wayback" (archived copies, for development) or "offline" (raw cache only)
    user_agent: str
    legislature: int


def settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql://parlament:parlament@127.0.0.1:5432/parlament"),
        data_dir=Path(os.environ.get("PARLAMENT_DATA_DIR", ROOT / "data")),
        request_delay=float(os.environ.get("PARLAMENT_REQUEST_DELAY", "3")),
        fetch_mode=os.environ.get("PARLAMENT_FETCH_MODE", "live"),
        user_agent=os.environ.get(
            "PARLAMENT_USER_AGENT",
            "parlament-transparenta/0.1 (+https://github.com/dmdafsm/parlament)",
        ),
        legislature=int(os.environ.get("PARLAMENT_LEGISLATURE", CURRENT_LEGISLATURE)),
    )
