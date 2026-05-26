from __future__ import annotations

from typing import Any

from app.errors import NotFoundError, PermissionRequiredError
from app.github.client import GithubClient
from app.github.url_parser import RepoRef


_PERMISSION_LEVELS = {
    "read": 1,
    "write": 2,
    "admin": 3,
}

_RELEASE_FIELDS = (
    "tag_name",
    "name",
    "published_at",
    "prerelease",
    "draft",
    "html_url",
)

_ACTIONS_RUN_FIELDS = (
    "id",
    "name",
    "status",
    "conclusion",
    "event",
    "created_at",
    "updated_at",
    "html_url",
)


class GithubAgentTools:
    def __init__(
        self,
        client: GithubClient,
        ref: RepoRef,
        private_mode: bool,
        permissions: dict[str, str] | Any,
    ):
        self.client = client
        self.ref = ref
        self.private_mode = private_mode
        self.permissions = permissions if isinstance(permissions, dict) else {}
        self.base = f"/repos/{ref.owner}/{ref.repo}"

    def get_repo_summary(self) -> dict[str, Any]:
        data = self.client.get_json(self.base)
        if not isinstance(data, dict):
            data = {}
        license_data = data.get("license")
        license_value = license_data.get("spdx_id") if isinstance(license_data, dict) else license_data
        return {
            "full_name": data.get("full_name") or self.ref.full_name,
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "archived": data.get("archived", False),
            "fork": data.get("fork", False),
            "default_branch": data.get("default_branch"),
            "license": license_value,
            "source": f"https://github.com/{self.ref.full_name}",
        }

    def get_language_breakdown(self) -> dict[str, Any]:
        data = self.client.get_json(f"{self.base}/languages")
        if not isinstance(data, dict):
            return {"total_bytes": 0, "languages": []}

        language_bytes = [
            (name, int(bytes_count))
            for name, bytes_count in data.items()
            if isinstance(name, str)
            and isinstance(bytes_count, (int, float))
            and not isinstance(bytes_count, bool)
            and bytes_count >= 0
        ]
        language_bytes.sort(key=lambda item: item[1], reverse=True)
        total_bytes = sum(bytes_count for _name, bytes_count in language_bytes)
        languages = [
            {
                "name": name,
                "bytes": bytes_count,
                "percentage": round((bytes_count / total_bytes) * 100, 1) if total_bytes else 0.0,
            }
            for name, bytes_count in language_bytes
        ]
        return {"total_bytes": total_bytes, "languages": languages}

    def get_releases(self) -> dict[str, Any]:
        releases = self.client.get_json(f"{self.base}/releases", params={"per_page": 10})
        if not isinstance(releases, list):
            return self._malformed_releases()

        items = [self._select_fields(release, _RELEASE_FIELDS) for release in releases if isinstance(release, dict)]
        return {"available": True, "count": len(items), "items": items}

    def get_actions_runs_summary(self) -> dict[str, Any]:
        if not self._has("actions", "read"):
            return self._unavailable("actions:read")

        try:
            runs = self.client.get_json(f"{self.base}/actions/runs", params={"per_page": 20})
        except PermissionRequiredError:
            return self._unavailable("actions:read")
        except NotFoundError:
            return {"available": False, "reason": "not_found"}

        if not isinstance(runs, dict):
            return self._malformed_actions_runs()

        workflow_runs = runs.get("workflow_runs", [])
        if not isinstance(workflow_runs, list):
            workflow_runs = []

        recent_runs = [
            self._select_fields(workflow_run, _ACTIONS_RUN_FIELDS)
            for workflow_run in workflow_runs
            if isinstance(workflow_run, dict)
        ]
        total_count = runs.get("total_count")
        if not isinstance(total_count, int) or isinstance(total_count, bool):
            total_count = len(recent_runs)
        return {
            "available": True,
            "total_count": total_count,
            "conclusion_counts": self._counts(recent_runs, "conclusion"),
            "status_counts": self._counts(recent_runs, "status"),
            "recent_runs": recent_runs,
        }

    def _has(self, permission: str, level: str) -> bool:
        granted = self.permissions.get(permission)
        granted_rank = _PERMISSION_LEVELS.get(granted or "")
        required_rank = _PERMISSION_LEVELS.get(level)
        if granted_rank is None or required_rank is None:
            return False
        return granted_rank >= required_rank

    @staticmethod
    def _unavailable(permission: str) -> dict[str, Any]:
        return {"available": False, "missing_permission": permission}

    @staticmethod
    def _malformed_releases() -> dict[str, Any]:
        return {"available": False, "error": "malformed_response", "count": 0, "items": []}

    @staticmethod
    def _malformed_actions_runs() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "total_count": 0,
            "conclusion_counts": {},
            "status_counts": {},
            "recent_runs": [],
        }

    @staticmethod
    def _select_fields(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        return {field: data.get(field) for field in fields}

    @staticmethod
    def _counts(items: list[dict[str, Any]], field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            value = item.get(field)
            if isinstance(value, str) and value:
                counts[value] = counts.get(value, 0) + 1
        return counts
