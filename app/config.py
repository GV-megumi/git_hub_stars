from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_FLASK_SECRET_KEY = "dev-only-change-me"


@dataclass(frozen=True)
class Settings:
    flask_env: str
    flask_secret_key: str
    github_app_id: str | None
    github_app_slug: str | None
    github_app_private_key_path: Path | None
    github_app_setup_url: str | None
    tavily_api_key: str | None
    model_base_url: str | None
    model_api_key: str | None
    model_name: str | None
    github_api_base_url: str = "https://api.github.com"

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        private_key_path = _env("GITHUB_APP_PRIVATE_KEY_PATH")
        return cls(
            flask_env=_env("FLASK_ENV") or "development",
            flask_secret_key=_env("FLASK_SECRET_KEY") or DEFAULT_FLASK_SECRET_KEY,
            github_app_id=_env("GITHUB_APP_ID"),
            github_app_slug=_env("GITHUB_APP_SLUG"),
            github_app_private_key_path=Path(private_key_path) if private_key_path else None,
            github_app_setup_url=_env("GITHUB_APP_SETUP_URL"),
            tavily_api_key=_env("TAVILY_API_KEY"),
            model_base_url=_env("MODEL_BASE_URL"),
            model_api_key=_env("MODEL_API_KEY"),
            model_name=_env("MODEL_NAME"),
            github_api_base_url=_env("GITHUB_API_BASE_URL") or "https://api.github.com",
        )

    @property
    def github_app_configured(self) -> bool:
        return all(
            [
                self.github_app_id,
                self.github_app_slug,
                self.github_app_private_key_path,
                self.github_app_setup_url,
            ]
        )

    @property
    def agent_configured(self) -> bool:
        return all([self.model_base_url, self.model_api_key, self.model_name])


def _env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None
