"""Configuration for the mock legal research backend.

All durations are in seconds and are configurable via env vars prefixed ``MOCK_``
(or a ``.env`` file). Durations are *means*; actual job durations are sampled
from a normal distribution and clamped to ``[min, max]``.

A ``MOCK_TIME_SCALE`` (default 1.0) multiplies both the sampled duration and the
inter-progress interval, so the whole system can be sped up for development
(e.g. ``MOCK_TIME_SCALE=0.01`` makes a ~2m quick job take ~1.2s) without
changing the progress semantics.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOCK_", env_file=".env", extra="ignore")

    # Storage (SQLModel is DB-agnostic; swap to postgres+asyncpg by changing this).
    db_url: str = "sqlite+aiosqlite:///./data/jobs.db"

    # Global acceleration factor for development.
    time_scale: float = 1.0

    # Effort-tier durations (seconds): mean / std / min / max.
    quick_mean_s: float = 120.0
    quick_sd_s: float = 15.0
    quick_min_s: float = 60.0
    quick_max_s: float = 180.0

    standard_mean_s: float = 300.0
    standard_sd_s: float = 60.0
    standard_min_s: float = 180.0
    standard_max_s: float = 600.0

    deep_mean_s: float = 720.0
    deep_sd_s: float = 180.0
    deep_min_s: float = 300.0
    deep_max_s: float = 1200.0

    # Probability that a job ends in `failed` instead of `completed`.
    failure_prob: float = 0.05

    # Progress reporting: events are emitted at random intervals. The mock, like
    # the real system, does NOT report a reliable ETA. Progress percentages are
    # noisy and may stall or briefly regress.
    progress_interval_mean_s: float = 8.0
    progress_interval_min_s: float = 2.0

    # Host/port for the dev server.
    host: str = "127.0.0.1"
    port: int = 8000


settings = Settings()
