from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import jwt
import requests

from app.errors import (
    GithubApiError,
    GithubRateLimitError,
    NotFoundError,
    PermissionRequiredError,
    ValidationError,
)

DEFAULT_INSTALLATION_TOKEN_PERMISSIONS = {
    "metadata": "read",
    "contents": "read",
}


class GithubAppAuth:
    def __init__(
        self,
        app_slug: str,
        app_id: str,
        private_key_path: Path,
        api_base_url: str = "https://api.github.com",
    ):
        self.app_slug = app_slug
        self.app_id = str(app_id)
        self.private_key_path = Path(private_key_path)
        self.api_base_url = api_base_url.rstrip("/")

    def install_url(self) -> str:
        return f"https://github.com/apps/{self.app_slug}/installations/new"

    def create_app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        private_key = self.private_key_path.read_text(encoding="utf-8")
        return jwt.encode(payload, private_key, algorithm="RS256")

    def create_installation_token(
        self,
        installation_id: str | int,
        repositories: list[str] | None = None,
        permissions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        installation_id = _installation_id(installation_id)
        path = f"/app/installations/{installation_id}/access_tokens"
        body: dict[str, Any] = {}
        if repositories is not None:
            body["repositories"] = _repository_names(repositories)
        requested_permissions = (
            DEFAULT_INSTALLATION_TOKEN_PERMISSIONS if permissions is None else permissions
        )
        body["permissions"] = _read_only_permissions(requested_permissions)

        try:
            response = requests.post(
                f"{self.api_base_url}{path}",
                json=body,
                headers=self._headers(),
                timeout=20,
            )
        except requests.RequestException as exc:
            raise _network_error(path, exc) from exc
        _raise_for_github_error(response, path)
        return response.json()

    def get_installation(self, installation_id: str | int) -> dict[str, Any]:
        installation_id = _installation_id(installation_id)
        path = f"/app/installations/{installation_id}"
        try:
            response = requests.get(
                f"{self.api_base_url}{path}",
                headers=self._headers(),
                timeout=20,
            )
        except requests.RequestException as exc:
            raise _network_error(path, exc) from exc
        _raise_for_github_error(response, path)
        return _installation_state(response.json())

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.create_app_jwt()}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "github-repo-health-tool",
        }


def _installation_id(value: str | int) -> str:
    if isinstance(value, bool):
        raise ValidationError("GitHub App installation_id must be numeric.")
    text = str(value)
    if not text.isdecimal():
        raise ValidationError("GitHub App installation_id must be numeric.")
    return text


def _repository_names(repositories: list[str]) -> list[str]:
    if not isinstance(repositories, list):
        raise ValidationError("GitHub App repositories must be a list of repository names.")
    names: list[str] = []
    for repository in repositories:
        if not isinstance(repository, str):
            raise ValidationError("GitHub App repository names must be strings.")
        name = repository.strip()
        if not name or "/" in name:
            raise ValidationError("GitHub App repositories must use repository names, not owner/repo full names.")
        names.append(name)
    return names


def _read_only_permissions(permissions: dict[str, str]) -> dict[str, str]:
    if not isinstance(permissions, dict):
        raise ValidationError("GitHub App installation token permissions must be an object.")

    read_permissions: dict[str, str] = {}
    for permission, level in permissions.items():
        if not isinstance(permission, str) or not permission.strip():
            raise ValidationError("GitHub App installation token permission names must be non-empty strings.")
        if level != "read":
            raise ValidationError("GitHub App installation token permissions must be read-only.")
        read_permissions[permission.strip()] = level
    return read_permissions


def _installation_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    state = {
        "id": payload.get("id"),
        "repository_selection": payload.get("repository_selection"),
        "permissions": payload.get("permissions") or {},
        "repositories": _installation_repositories(payload.get("repositories")),
    }
    account = payload.get("account")
    if isinstance(account, dict):
        state["account"] = {
            key: account[key]
            for key in ("login", "type", "id")
            if key in account
        }
    else:
        state["account"] = None
    return state


def _installation_repositories(repositories: Any) -> list[str]:
    if not isinstance(repositories, list):
        return []

    names: list[str] = []
    for repository in repositories:
        if not isinstance(repository, dict):
            continue
        name = repository.get("full_name") or repository.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def _raise_for_github_error(response: requests.Response, path: str) -> None:
    if response.status_code < 400:
        return

    github_message = _extract_github_message(response)
    message = _error_message(response.status_code, github_message)
    kwargs = {
        "github_status_code": response.status_code,
        "github_path": path,
        "github_message": github_message,
    }
    if _is_rate_limit_response(response, github_message):
        raise GithubRateLimitError(
            message,
            **kwargs,
            rate_limit_remaining=response.headers.get("X-RateLimit-Remaining"),
            rate_limit_reset=response.headers.get("X-RateLimit-Reset"),
            retry_after=response.headers.get("Retry-After"),
        )
    if response.status_code == 404:
        raise NotFoundError(message, **kwargs)
    if response.status_code in {401, 403}:
        raise PermissionRequiredError(message, **kwargs)
    if response.status_code == 422:
        raise ValidationError(message, **kwargs)
    raise GithubApiError(message, **kwargs)


def _network_error(path: str, exc: requests.RequestException) -> GithubApiError:
    return GithubApiError(
        f"GitHub App API request failed: {exc}.",
        github_path=path,
    )


def _error_message(status_code: int, github_message: str | None) -> str:
    detail = f": {github_message}" if github_message else ""
    return f"GitHub App API request failed: HTTP {status_code}{detail}"


def _extract_github_message(response: requests.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or None
    if isinstance(payload, dict):
        message = payload.get("message")
        return str(message) if message else None
    return None


def _is_rate_limit_response(response: requests.Response, github_message: str | None) -> bool:
    if response.status_code not in {403, 429}:
        return False
    if response.status_code == 429:
        return True
    if response.headers.get("X-RateLimit-Remaining") == "0":
        return True
    return bool(github_message and "rate limit" in github_message.lower())
