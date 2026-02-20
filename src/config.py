"""Application configuration: loads .env secrets + settings.yaml."""

from __future__ import annotations

import logging.config
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: SecretStr
    telegram_channel_id: int = -100
    telegram_admin_ids: str = ""

    # AI
    anthropic_api_key: SecretStr = SecretStr("")

    # Search
    tavily_api_key: SecretStr = SecretStr("")

    # Database
    database_url: str = f"sqlite+aiosqlite:///{DATA_DIR / 'bot.db'}"

    # Web
    web_secret_key: SecretStr = SecretStr("change-me")
    web_host: str = "0.0.0.0"
    web_port: int = 8000

    # Agency42 (Instagram)
    ig_username: str = ""
    ig_password: SecretStr = SecretStr("")

    # Non-secret config from YAML
    agents: dict[str, Any] = Field(default_factory=dict)
    pipeline: dict[str, Any] = Field(default_factory=dict)
    log_level: str = "INFO"

    @field_validator("telegram_admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, v: Any) -> str:
        if isinstance(v, list):
            return ",".join(str(i) for i in v)
        return str(v)

    @property
    def admin_ids_list(self) -> list[int]:
        if not self.telegram_admin_ids:
            return []
        return [int(x.strip()) for x in self.telegram_admin_ids.split(",") if x.strip()]

    def get_agent_config(self, agent_name: str) -> dict[str, Any]:
        return self.agents.get(agent_name, {})


def setup_logging() -> None:
    logging_yaml = CONFIG_DIR / "logging.yaml"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if logging_yaml.exists():
        cfg = _load_yaml(logging_yaml)
        logging.config.dictConfig(cfg)
    else:
        logging.basicConfig(level=logging.INFO)


@lru_cache
def get_settings() -> Settings:
    yaml_config = _load_yaml(CONFIG_DIR / "settings.yaml")
    return Settings(
        agents=yaml_config.get("agents", {}),
        pipeline=yaml_config.get("pipeline", {}),
        log_level=yaml_config.get("log_level", "INFO"),
    )
