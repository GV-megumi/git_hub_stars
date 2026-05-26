from __future__ import annotations

from typing import Any

import requests

from app.errors import (
    GithubApiError,
    GithubRateLimitError,
    NotFoundError,
    PermissionRequiredError,
    ValidationError,
)


class GithubClient:
    def __init__(self, base_url: str = "https://api.github.com", token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._is_valid_path(path):
            raise ValidationError("GitHub API path must be an internal path starting with '/'.")

        response = requests.get(
            f"{self.base_url}{path}",
            params=params,
            headers=self._headers(),
            timeout=20,
        )
        github_message = self._github_message(response)
        if self._is_rate_limit_response(response, github_message):
            raise GithubRateLimitError(
                github_message or "GitHub API rate limit was exceeded.",
                github_status_code=response.status_code,
                github_path=path,
                github_message=github_message,
                rate_limit_remaining=response.headers.get("X-RateLimit-Remaining"),
                rate_limit_reset=response.headers.get("X-RateLimit-Reset"),
                retry_after=response.headers.get("Retry-After"),
            )
        if response.status_code == 404:
            raise NotFoundError(
                "GitHub repository was not found.",
                github_status_code=response.status_code,
                github_path=path,
                github_message=github_message,
            )
        if response.status_code in {401, 403}:
            raise PermissionRequiredError(
                "GitHub API permission is required.",
                github_status_code=response.status_code,
                github_path=path,
                github_message=github_message,
            )
        if response.status_code >= 400:
            detail = github_message or f"HTTP {response.status_code}"
            raise GithubApiError(
                f"GitHub API request failed: {detail}.",
                github_status_code=response.status_code,
                github_path=path,
                github_message=github_message,
            )
        return response.json()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-repo-health-tool",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    @staticmethod
    def _is_valid_path(path: object) -> bool:
        if not isinstance(path, str):
            return False
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            return False
        return not any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in path)

    @staticmethod
    def _github_message(response: requests.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, str):
                return message
        return None

    @staticmethod
    def _is_rate_limit_response(response: requests.Response, github_message: str | None) -> bool:
        if response.status_code not in {403, 429}:
            return False
        if response.status_code == 429:
            return True
        if response.headers.get("X-RateLimit-Remaining") == "0":
            return True
        return bool(github_message and "rate limit" in github_message.lower())
