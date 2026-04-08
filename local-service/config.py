from __future__ import annotations

import yaml
from pathlib import Path
from typing import Literal
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    github_token: str
    github_repo: str

    slack_bot_token: str
    slack_signing_secret: str
    slack_channel: str

    webhook_secret: str

    review_mode: Literal["manual", "auto"] = "manual"
    allowed_slack_users: list[str] = Field(default_factory=list)

    model_config = {"env_prefix": "", "case_sensitive": False}


def load_settings(config_path: str | Path = "config.yml") -> Settings:
    """Load settings from YAML file, with env var overrides."""
    path = Path(config_path)
    file_values: dict = {}
    if path.exists():
        with open(path) as f:
            file_values = yaml.safe_load(f) or {}
    return Settings(**file_values)
