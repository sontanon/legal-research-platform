"""Env-driven settings for the MCP adapter."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MCP_", env_file=".env", extra="ignore")

    backend_url: str = "http://127.0.0.1:8000"
    host: str = "127.0.0.1"
    port: int = 8001
    auth_token: str = ""

    widget_poll_ms: int = 1500
    three_tool_hold_ms: int = 25000
    hold_poll_interval_s: int = 2


settings = Settings()
