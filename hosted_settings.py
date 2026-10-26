"""Environment configuration for the bounded, single-machine public demo."""

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class HostedSettings:
    """Keep hosting state separate from the original research data and API token."""

    root: Path
    origins: tuple[str, ...] = ("http://localhost:8000", "http://127.0.0.1:8000")
    timeout_seconds: int = 180
    max_pending: int = 4
    per_ip_hour: int = 3
    global_daily: int = 12
    retention_hours: int = 24
    seed_directory: Path = PROJECT / "deployment" / "seed"

    @classmethod
    def from_environment(cls):
        return cls(
            root=Path(os.environ.get("HOSTED_STATE_DIR", PROJECT / "data" / "hosted")),
            origins=tuple(
                origin.strip().rstrip("/")
                for origin in os.environ.get(
                    "ALLOWED_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
                ).split(",")
                if origin.strip()
            ),
            timeout_seconds=int(os.environ.get("JOB_TIMEOUT_SECONDS", "180")),
            seed_directory=Path(os.environ.get("HOSTED_SEED_DIR", PROJECT / "deployment" / "seed")),
        )
