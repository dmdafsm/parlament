"""Runtime settings from environment variables (12-factor); defaults suit local development."""

import os
from dataclasses import dataclass, field
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
    on_block: str = "stop"  # "stop" the run at a bot check, or "skip": record the page, pause, go on
    block_cooldown: float = 600.0  # seconds to pause after a bot check in "skip" mode
    block_limit: int = 3  # consecutive bot checks after which even "skip" mode stops
    # Local language model for plain-language summaries (OpenAI-compatible endpoint, ADR 0006).
    llm_url: str = "http://127.0.0.1:8091/v1"
    llm_model: str = "default_model"  # name sent to the server; mlx_lm.server answers with the model it loaded
    llm_label: str = "RoGemma3-4B-Instruct (OpenLLM-Ro)"  # shown next to each summary
    # Weekly data release on GitHub (ADR 0008); without a token the scheduler skips it.
    github_repo: str = "dmdafsm/parlament"
    github_token: str = field(default="", repr=False)


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
        on_block=os.environ.get("PARLAMENT_ON_BLOCK", "stop"),
        block_cooldown=float(os.environ.get("PARLAMENT_BLOCK_COOLDOWN", "600")),
        block_limit=int(os.environ.get("PARLAMENT_BLOCK_LIMIT", "3")),
        llm_url=os.environ.get("PARLAMENT_LLM_URL", "http://127.0.0.1:8091/v1"),
        llm_model=os.environ.get("PARLAMENT_LLM_MODEL", "default_model"),
        llm_label=os.environ.get("PARLAMENT_LLM_LABEL", "RoGemma3-4B-Instruct (OpenLLM-Ro)"),
        github_repo=os.environ.get("PARLAMENT_GITHUB_REPO", "dmdafsm/parlament"),
        github_token=os.environ.get("PARLAMENT_GITHUB_TOKEN", ""),
    )
