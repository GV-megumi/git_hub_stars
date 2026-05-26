from __future__ import annotations

import base64
import math
from typing import Any
from urllib.parse import urlparse

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

_COMMUNITY_FILE_KEYS = (
    "readme",
    "license",
    "contributing",
    "code_of_conduct",
    "issue_template",
    "pull_request_template",
    "security",
)

_CHECK_RUN_FIELDS = (
    "id",
    "name",
    "status",
    "conclusion",
    "started_at",
    "completed_at",
    "html_url",
)

_RULESET_FIELDS = (
    "id",
    "name",
    "target",
    "enforcement",
    "source_type",
)

_SECURITY_ADVISORY_FIELDS = (
    "ghsa_id",
    "cve_id",
    "state",
    "severity",
    "published_at",
    "updated_at",
    "html_url",
)

_DEPLOYMENT_FIELDS = (
    "id",
    "environment",
    "ref",
    "sha",
    "task",
    "created_at",
    "updated_at",
    "transient_environment",
    "production_environment",
)

_KEY_FILES = (
    ("readme", "README.md", None),
    ("contributing", "CONTRIBUTING.md", "CONTRIBUTING.md"),
    ("security", "SECURITY.md", "SECURITY.md"),
    ("code_of_conduct", "CODE_OF_CONDUCT.md", "CODE_OF_CONDUCT.md"),
)

_MAX_RECENT_COMMITS = 30
_MAX_RECENT_ISSUES = 30
_MAX_RECENT_PULLS = 30
_MAX_CHECK_RUNS = 50
_MAX_RULESETS = 30
_MAX_SECURITY_ADVISORIES = 50
_MAX_DEPLOYMENTS = 30
_MAX_FILE_TEXT_CHARS = 1200
_MAX_FILE_SIZE_TO_DECODE = 120_000
_MAX_SBOM_PACKAGES = 20
_MAX_ALERT_SUMMARIES = 10
_MAX_TRAFFIC_TOP_ITEMS = 10


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

    def get_community_profile(self) -> dict[str, Any]:
        try:
            data = self.client.get_json(f"{self.base}/community/profile")
        except PermissionRequiredError:
            return self._unavailable("metadata:read")
        except NotFoundError:
            return {"available": False, "reason": "not_found"}

        if not isinstance(data, dict):
            return self._malformed_community_profile()

        return {
            "available": True,
            "health_percentage": data.get("health_percentage"),
            "files": self._community_file_booleans(data.get("files")),
        }

    def get_recent_commits(self) -> dict[str, Any]:
        if self.private_mode and not self._has("contents", "read"):
            return self._unavailable("contents:read")

        commits = self.client.get_json(f"{self.base}/commits", params={"per_page": _MAX_RECENT_COMMITS})
        if not isinstance(commits, list):
            return self._malformed_recent_commits()

        items = [self._commit_summary(commit) for commit in commits if isinstance(commit, dict)]
        return {"available": True, "count": len(items), "items": items}

    def get_issues_summary(self) -> dict[str, Any]:
        if self.private_mode and not self._has("issues", "read"):
            return self._unavailable("issues:read")

        issues = self.client.get_json(
            f"{self.base}/issues",
            params={"state": "open", "per_page": _MAX_RECENT_ISSUES},
        )
        if not isinstance(issues, list):
            return self._malformed_issues()

        issue_items = [
            issue
            for issue in issues
            if isinstance(issue, dict) and not isinstance(issue.get("pull_request"), dict)
        ]
        summaries = [self._issue_summary(issue) for issue in issue_items]
        return {
            "available": True,
            "open_count": len(summaries),
            "label_counts": self._label_counts(summaries),
            "recent_issues": summaries,
        }

    def get_pulls_summary(self) -> dict[str, Any]:
        if self.private_mode and not self._has("pull_requests", "read"):
            return self._unavailable("pull_requests:read")

        pulls = self.client.get_json(
            f"{self.base}/pulls",
            params={"state": "open", "per_page": _MAX_RECENT_PULLS},
        )
        if not isinstance(pulls, list):
            return self._malformed_pulls()

        summaries = [self._pull_summary(pull) for pull in pulls if isinstance(pull, dict)]
        return {
            "available": True,
            "open_count": len(summaries),
            "draft_count": sum(1 for pull in summaries if pull.get("draft") is True),
            "recent_pulls": summaries,
        }

    def get_releases(self) -> dict[str, Any]:
        releases = self.client.get_json(f"{self.base}/releases", params={"per_page": 10})
        if not isinstance(releases, list):
            return self._malformed_releases()

        items = [self._select_fields(release, _RELEASE_FIELDS) for release in releases if isinstance(release, dict)]
        return {"available": True, "count": len(items), "items": items}

    def get_actions_runs_summary(self) -> dict[str, Any]:
        if self.private_mode and not self._has("actions", "read"):
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

    def get_readme_and_key_files(self) -> dict[str, Any]:
        if self.private_mode and not self._has("contents", "read"):
            return self._unavailable("contents:read")

        files: list[dict[str, Any]] = []
        for key, display_path, content_path in _KEY_FILES:
            endpoint = f"{self.base}/readme" if content_path is None else f"{self.base}/contents/{content_path}"
            try:
                data = self.client.get_json(endpoint)
            except PermissionRequiredError:
                return self._unavailable("contents:read")
            except NotFoundError:
                files.append({"key": key, "available": False, "reason": "not_found", "path": display_path})
                continue

            if not isinstance(data, dict):
                files.append({"key": key, "available": False, "error": "malformed_response", "path": display_path})
                continue
            files.append(self._key_file_summary(key, data))

        return {"available": True, "files": files}

    def get_traffic_summary(self) -> dict[str, Any]:
        permission = "administration:read"
        if not self._has("administration", "read"):
            return self._unavailable(permission)

        ok, views = self._get_json_or_unavailable(f"{self.base}/traffic/views", permission)
        if not ok:
            return views
        ok, clones = self._get_json_or_unavailable(f"{self.base}/traffic/clones", permission)
        if not ok:
            return clones
        ok, referrers = self._get_json_or_unavailable(f"{self.base}/traffic/popular/referrers", permission)
        if not ok:
            return referrers
        ok, paths = self._get_json_or_unavailable(f"{self.base}/traffic/popular/paths", permission)
        if not ok:
            return paths

        if (
            not isinstance(views, dict)
            or not isinstance(clones, dict)
            or not isinstance(referrers, list)
            or not isinstance(paths, list)
        ):
            return self._malformed_traffic()

        return {
            "available": True,
            "views": self._traffic_totals(views),
            "clones": self._traffic_totals(clones),
            "referrers": self._traffic_referrers(referrers),
            "paths": self._traffic_paths(paths),
        }

    def get_sbom_summary(self) -> dict[str, Any]:
        permission = "contents:read"
        if not self._has("contents", "read"):
            return self._unavailable(permission)

        ok, data = self._get_json_or_unavailable(f"{self.base}/dependency-graph/sbom/generate-report", permission)
        if not ok:
            return data

        if not isinstance(data, dict):
            return self._malformed_sbom()
        summary = self._sbom_summary_from_response(data)
        if summary is not None:
            return summary

        fetch_path = self._same_origin_sbom_fetch_path(data.get("sbom_url"))
        if fetch_path is None:
            if isinstance(data.get("sbom_url"), str):
                return self._sbom_report_requested("report_requested")
            return self._malformed_sbom()

        try:
            fetched = self.client.get_json(fetch_path, allow_redirects=False)
        except PermissionRequiredError:
            return self._unavailable(permission)
        except NotFoundError:
            return self._sbom_report_requested("processing")

        if not isinstance(fetched, dict):
            return self._sbom_report_requested("processing")
        if fetched.get("status_code") == 202:
            return self._sbom_report_requested("processing")
        if fetched.get("status_code") == 302:
            return self._sbom_report_requested("report_ready")
        summary = self._sbom_summary_from_response(fetched)
        if summary is None:
            return self._sbom_report_requested("processing")
        return summary

    def _sbom_summary_from_response(self, data: dict[str, Any]) -> dict[str, Any] | None:
        if "status_code" in data:
            return None
        sbom = data.get("sbom")
        if not isinstance(sbom, dict):
            return None
        packages = sbom.get("packages", [])
        if not isinstance(packages, list):
            return None

        package_summaries = [
            summary
            for summary in (self._sbom_package_summary(package) for package in packages[:_MAX_SBOM_PACKAGES])
            if summary is not None
        ]
        return {
            "available": True,
            "package_count": len(packages),
            "packages": package_summaries,
        }

    def get_dependabot_alerts_summary(self) -> dict[str, Any]:
        permission = "vulnerability_alerts:read"
        if not self._has("vulnerability_alerts", "read"):
            return self._unavailable(permission)

        ok, alerts = self._get_json_or_unavailable(
            f"{self.base}/dependabot/alerts",
            permission,
            params={"per_page": 100},
        )
        if not ok:
            return alerts
        if not isinstance(alerts, list):
            return self._malformed_dependabot_alerts()

        alert_items = [alert for alert in alerts if isinstance(alert, dict)]
        return {
            "available": True,
            "open_alerts": self._open_alert_count(alert_items),
            "severity_counts": self._counts_by_value(alert_items, self._dependabot_severity),
            "state_counts": self._counts(alert_items, "state"),
            "alerts": [
                self._dependabot_alert_summary(alert)
                for alert in alert_items[:_MAX_ALERT_SUMMARIES]
            ],
        }

    def get_code_scanning_alerts_summary(self) -> dict[str, Any]:
        permission = "security_events:read"
        if not self._has("security_events", "read"):
            return self._unavailable(permission)

        ok, alerts = self._get_json_or_unavailable(
            f"{self.base}/code-scanning/alerts",
            permission,
            params={"per_page": 100},
        )
        if not ok:
            return alerts
        if not isinstance(alerts, list):
            return self._malformed_code_scanning_alerts()

        alert_items = [alert for alert in alerts if isinstance(alert, dict)]
        return {
            "available": True,
            "open_alerts": self._open_alert_count(alert_items),
            "severity_counts": self._counts_by_value(alert_items, self._code_scanning_severity),
            "rule_counts": self._counts_by_value(alert_items, self._code_scanning_rule_id),
            "state_counts": self._counts(alert_items, "state"),
            "alerts": [
                self._code_scanning_alert_summary(alert)
                for alert in alert_items[:_MAX_ALERT_SUMMARIES]
            ],
        }

    def get_secret_scanning_alerts_summary(self) -> dict[str, Any]:
        permission = "secret_scanning_alerts:read"
        if not self._has("secret_scanning_alerts", "read"):
            return self._unavailable(permission)

        ok, alerts = self._get_json_or_unavailable(
            f"{self.base}/secret-scanning/alerts",
            permission,
            params={"per_page": 100},
        )
        if not ok:
            return alerts
        if not isinstance(alerts, list):
            return self._malformed_secret_scanning_alerts()

        alert_items = [alert for alert in alerts if isinstance(alert, dict)]
        return {
            "available": True,
            "open_alerts": self._open_alert_count(alert_items),
            "state_counts": self._counts(alert_items, "state"),
            "secret_type_counts": self._counts(alert_items, "secret_type"),
            "alerts": [
                self._secret_scanning_alert_summary(alert)
                for alert in alert_items[:_MAX_ALERT_SUMMARIES]
            ],
        }

    def get_checks_summary(self) -> dict[str, Any]:
        permission = "checks:read"
        if not self._has("checks", "read"):
            return self._unavailable(permission)

        try:
            default_branch = self._default_branch()
        except PermissionRequiredError:
            return self._unavailable(permission)
        except NotFoundError:
            return {"available": False, "reason": "not_found"}
        if not default_branch:
            return self._malformed_checks()

        ok, runs = self._get_json_or_unavailable(
            f"{self.base}/commits/{default_branch}/check-runs",
            permission,
            params={"per_page": _MAX_CHECK_RUNS},
        )
        if not ok:
            return runs
        if not isinstance(runs, dict):
            return self._malformed_checks()

        check_runs = runs.get("check_runs", [])
        if not isinstance(check_runs, list):
            check_runs = []
        recent_runs = [
            self._select_fields(check_run, _CHECK_RUN_FIELDS)
            for check_run in check_runs
            if isinstance(check_run, dict)
        ]
        total_count = runs.get("total_count")
        if not isinstance(total_count, int) or isinstance(total_count, bool):
            total_count = len(recent_runs)
        return {
            "available": True,
            "total_count": total_count,
            "status_counts": self._counts(recent_runs, "status"),
            "conclusion_counts": self._counts(recent_runs, "conclusion"),
            "recent_runs": recent_runs,
        }

    def get_repository_rules_summary(self) -> dict[str, Any]:
        permission = "administration:read"
        if not self._has("administration", "read"):
            return self._unavailable(permission)

        ok, rulesets = self._get_json_or_unavailable(
            f"{self.base}/rulesets",
            permission,
            params={"per_page": _MAX_RULESETS},
        )
        if not ok:
            return rulesets
        if not isinstance(rulesets, list):
            return self._malformed_rulesets()

        items = [self._select_fields(ruleset, _RULESET_FIELDS) for ruleset in rulesets if isinstance(ruleset, dict)]
        return {"available": True, "count": len(items), "items": items}

    def get_security_advisories_summary(self) -> dict[str, Any]:
        permission = "repository_advisories:read"
        if not self._has("repository_advisories", "read"):
            return self._unavailable(permission)

        ok, advisories = self._get_json_or_unavailable(
            f"{self.base}/security-advisories",
            permission,
            params={"per_page": _MAX_SECURITY_ADVISORIES},
        )
        if not ok:
            return advisories
        if not isinstance(advisories, list):
            return self._malformed_security_advisories()

        items = [
            self._select_fields(advisory, _SECURITY_ADVISORY_FIELDS)
            for advisory in advisories
            if isinstance(advisory, dict)
        ]
        return {
            "available": True,
            "count": len(items),
            "state_counts": self._counts(items, "state"),
            "severity_counts": self._counts(items, "severity"),
            "items": items,
        }

    def get_deployments_summary(self) -> dict[str, Any]:
        permission = "deployments:read"
        if not self._has("deployments", "read"):
            return self._unavailable(permission)

        ok, deployments = self._get_json_or_unavailable(
            f"{self.base}/deployments",
            permission,
            params={"per_page": _MAX_DEPLOYMENTS},
        )
        if not ok:
            return deployments
        if not isinstance(deployments, list):
            return self._malformed_deployments()

        items = [
            self._select_fields(deployment, _DEPLOYMENT_FIELDS)
            for deployment in deployments
            if isinstance(deployment, dict)
        ]
        return {
            "available": True,
            "count": len(items),
            "environment_counts": self._counts(items, "environment"),
            "recent_deployments": items,
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
    def _malformed_community_profile() -> dict[str, Any]:
        return {"available": False, "error": "malformed_response", "health_percentage": None, "files": {}}

    @staticmethod
    def _malformed_recent_commits() -> dict[str, Any]:
        return {"available": False, "error": "malformed_response", "count": 0, "items": []}

    @staticmethod
    def _malformed_issues() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "open_count": 0,
            "label_counts": {},
            "recent_issues": [],
        }

    @staticmethod
    def _malformed_pulls() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "open_count": 0,
            "draft_count": 0,
            "recent_pulls": [],
        }

    @staticmethod
    def _malformed_traffic() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "views": {"count": 0, "uniques": 0},
            "clones": {"count": 0, "uniques": 0},
            "referrers": [],
            "paths": [],
        }

    @staticmethod
    def _malformed_sbom() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "package_count": 0,
            "packages": [],
        }

    @staticmethod
    def _sbom_report_requested(status: str) -> dict[str, Any]:
        return {
            "available": True,
            "status": status,
            "package_count": 0,
            "packages": [],
        }

    @staticmethod
    def _malformed_dependabot_alerts() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "open_alerts": 0,
            "severity_counts": {},
            "state_counts": {},
            "alerts": [],
        }

    @staticmethod
    def _malformed_code_scanning_alerts() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "open_alerts": 0,
            "severity_counts": {},
            "rule_counts": {},
            "state_counts": {},
            "alerts": [],
        }

    @staticmethod
    def _malformed_secret_scanning_alerts() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "open_alerts": 0,
            "state_counts": {},
            "secret_type_counts": {},
            "alerts": [],
        }

    @staticmethod
    def _malformed_checks() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "total_count": 0,
            "status_counts": {},
            "conclusion_counts": {},
            "recent_runs": [],
        }

    @staticmethod
    def _malformed_rulesets() -> dict[str, Any]:
        return {"available": False, "error": "malformed_response", "count": 0, "items": []}

    @staticmethod
    def _malformed_security_advisories() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "count": 0,
            "state_counts": {},
            "severity_counts": {},
            "items": [],
        }

    @staticmethod
    def _malformed_deployments() -> dict[str, Any]:
        return {
            "available": False,
            "error": "malformed_response",
            "count": 0,
            "environment_counts": {},
            "recent_deployments": [],
        }

    def _get_json_or_unavailable(
        self,
        path: str,
        permission: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[bool, Any]:
        try:
            return True, self.client.get_json(path, params=params)
        except PermissionRequiredError:
            return False, self._unavailable(permission)
        except NotFoundError:
            return False, {"available": False, "reason": "not_found"}

    @staticmethod
    def _select_fields(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
        return {field: data.get(field) for field in fields}

    @staticmethod
    def _community_file_booleans(files: Any) -> dict[str, bool]:
        if not isinstance(files, dict):
            return {key: False for key in _COMMUNITY_FILE_KEYS}
        return {key: bool(files.get(key)) for key in _COMMUNITY_FILE_KEYS}

    @staticmethod
    def _commit_summary(commit: dict[str, Any]) -> dict[str, Any]:
        commit_data = commit.get("commit")
        if not isinstance(commit_data, dict):
            commit_data = {}
        author_data = commit.get("author")
        commit_author = commit_data.get("author")
        if not isinstance(commit_author, dict):
            commit_author = {}
        if isinstance(author_data, dict) and isinstance(author_data.get("login"), str):
            author = author_data.get("login")
        else:
            author = commit_author.get("name")
        return {
            "sha": GithubAgentTools._short_sha(commit.get("sha")),
            "author": author,
            "message": GithubAgentTools._first_line(commit_data.get("message"), limit=140),
            "committed_at": commit_author.get("date"),
            "html_url": commit.get("html_url"),
        }

    @staticmethod
    def _issue_summary(issue: dict[str, Any]) -> dict[str, Any]:
        labels = GithubAgentTools._label_names(issue.get("labels"))
        return {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "state": issue.get("state"),
            "created_at": issue.get("created_at"),
            "updated_at": issue.get("updated_at"),
            "labels": labels,
            "html_url": issue.get("html_url"),
        }

    @staticmethod
    def _pull_summary(pull: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": pull.get("number"),
            "title": pull.get("title"),
            "state": pull.get("state"),
            "draft": pull.get("draft"),
            "created_at": pull.get("created_at"),
            "updated_at": pull.get("updated_at"),
            "html_url": pull.get("html_url"),
        }

    @staticmethod
    def _label_names(labels: Any) -> list[str]:
        names: list[str] = []
        if not isinstance(labels, list):
            return names
        for label in labels:
            if not isinstance(label, dict):
                continue
            name = label.get("name")
            if isinstance(name, str) and name:
                names.append(name)
        return names

    @staticmethod
    def _label_counts(items: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            labels = item.get("labels")
            if not isinstance(labels, list):
                continue
            for label in labels:
                if isinstance(label, str) and label:
                    counts[label] = counts.get(label, 0) + 1
        return counts

    @staticmethod
    def _short_sha(value: Any) -> Any:
        if isinstance(value, str):
            return value[:7]
        return value

    @staticmethod
    def _first_line(value: Any, limit: int) -> Any:
        if not isinstance(value, str):
            return value
        first_line = value.splitlines()[0] if value.splitlines() else ""
        return first_line[:limit]

    def _key_file_summary(self, key: str, data: dict[str, Any]) -> dict[str, Any]:
        text_excerpt = self._decode_key_file_excerpt(data)
        text_length = len(text_excerpt) if isinstance(text_excerpt, str) else 0
        original_text_length = self._decoded_key_file_text_length(data)
        return {
            "key": key,
            "available": True,
            "name": data.get("name"),
            "path": data.get("path"),
            "size": self._safe_int(data.get("size")),
            "html_url": data.get("html_url"),
            "text_excerpt": text_excerpt,
            "text_truncated": original_text_length > text_length,
        }

    @staticmethod
    def _decode_key_file_excerpt(data: dict[str, Any]) -> str | None:
        text = GithubAgentTools._decode_key_file_text(data)
        if text is None:
            return None
        return text[:_MAX_FILE_TEXT_CHARS]

    @staticmethod
    def _decoded_key_file_text_length(data: dict[str, Any]) -> int:
        text = GithubAgentTools._decode_key_file_text(data)
        return len(text) if isinstance(text, str) else 0

    @staticmethod
    def _decode_key_file_text(data: dict[str, Any]) -> str | None:
        size = data.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or size > _MAX_FILE_SIZE_TO_DECODE:
            return None
        content = data.get("content")
        if not isinstance(content, str) or data.get("encoding") != "base64":
            return None
        try:
            raw = base64.b64decode("".join(content.split()), validate=True)
        except (ValueError, TypeError):
            return None
        return raw.decode("utf-8", errors="replace")

    def _default_branch(self) -> str | None:
        data = self.client.get_json(self.base)
        if not isinstance(data, dict):
            return None
        branch = data.get("default_branch")
        return branch if isinstance(branch, str) and branch else None

    @staticmethod
    def _counts(items: list[dict[str, Any]], field: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            value = item.get(field)
            if isinstance(value, str) and value:
                counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _counts_by_value(items: list[dict[str, Any]], getter: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            value = getter(item)
            if isinstance(value, str) and value:
                counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _open_alert_count(alerts: list[dict[str, Any]]) -> int:
        return sum(1 for alert in alerts if alert.get("state") == "open")

    @staticmethod
    def _traffic_totals(data: dict[str, Any]) -> dict[str, int]:
        return {
            "count": GithubAgentTools._safe_int(data.get("count")),
            "uniques": GithubAgentTools._safe_int(data.get("uniques")),
        }

    @staticmethod
    def _safe_int(value: Any) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, float) and not math.isfinite(value):
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        return 0

    @staticmethod
    def _traffic_referrers(items: list[Any]) -> list[dict[str, Any]]:
        summaries = []
        for item in items[:_MAX_TRAFFIC_TOP_ITEMS]:
            if not isinstance(item, dict):
                continue
            summaries.append(
                {
                    "referrer": item.get("referrer"),
                    "count": GithubAgentTools._safe_int(item.get("count")),
                    "uniques": GithubAgentTools._safe_int(item.get("uniques")),
                }
            )
        return summaries

    @staticmethod
    def _traffic_paths(items: list[Any]) -> list[dict[str, Any]]:
        summaries = []
        for item in items[:_MAX_TRAFFIC_TOP_ITEMS]:
            if not isinstance(item, dict):
                continue
            summaries.append(
                {
                    "path": item.get("path"),
                    "title": item.get("title"),
                    "count": GithubAgentTools._safe_int(item.get("count")),
                    "uniques": GithubAgentTools._safe_int(item.get("uniques")),
                }
            )
        return summaries

    def _same_origin_sbom_fetch_path(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        parsed = urlparse(value)
        base_url = getattr(self.client, "base_url", "https://api.github.com")
        parsed_base = urlparse(base_url)
        if parsed.scheme != parsed_base.scheme or parsed.netloc != parsed_base.netloc:
            return None
        expected_prefix = f"{self.base}/dependency-graph/sbom/fetch-report/"
        if parsed.params or parsed.query or parsed.fragment:
            return None
        if not parsed.path.startswith(expected_prefix):
            return None
        return parsed.path

    @staticmethod
    def _sbom_package_summary(package: Any) -> dict[str, Any] | None:
        if not isinstance(package, dict):
            return None
        return {
            "name": package.get("name"),
            "version": package.get("versionInfo") or package.get("version"),
        }

    @staticmethod
    def _dependabot_alert_summary(alert: dict[str, Any]) -> dict[str, Any]:
        package = GithubAgentTools._dependabot_package(alert)
        return {
            "number": alert.get("number"),
            "state": alert.get("state"),
            "severity": GithubAgentTools._dependabot_severity(alert),
            "package": package.get("name"),
            "ecosystem": package.get("ecosystem"),
            "html_url": alert.get("html_url"),
        }

    @staticmethod
    def _dependabot_severity(alert: dict[str, Any]) -> Any:
        vulnerability = alert.get("security_vulnerability")
        if not isinstance(vulnerability, dict):
            return None
        return vulnerability.get("severity")

    @staticmethod
    def _dependabot_package(alert: dict[str, Any]) -> dict[str, Any]:
        dependency = alert.get("dependency")
        if isinstance(dependency, dict):
            package = dependency.get("package")
            if isinstance(package, dict):
                return package
        vulnerability = alert.get("security_vulnerability")
        if isinstance(vulnerability, dict):
            package = vulnerability.get("package")
            if isinstance(package, dict):
                return package
        return {}

    @staticmethod
    def _code_scanning_alert_summary(alert: dict[str, Any]) -> dict[str, Any]:
        tool = alert.get("tool")
        return {
            "number": alert.get("number"),
            "state": alert.get("state"),
            "rule_id": GithubAgentTools._code_scanning_rule_id(alert),
            "severity": GithubAgentTools._code_scanning_severity(alert),
            "tool": tool.get("name") if isinstance(tool, dict) else None,
            "html_url": alert.get("html_url"),
        }

    @staticmethod
    def _code_scanning_rule_id(alert: dict[str, Any]) -> Any:
        rule = alert.get("rule")
        if not isinstance(rule, dict):
            return None
        return rule.get("id")

    @staticmethod
    def _code_scanning_severity(alert: dict[str, Any]) -> Any:
        rule = alert.get("rule")
        if not isinstance(rule, dict):
            return None
        return rule.get("security_severity_level") or rule.get("severity")

    @staticmethod
    def _secret_scanning_alert_summary(alert: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": alert.get("number"),
            "state": alert.get("state"),
            "secret_type": alert.get("secret_type"),
            "html_url": alert.get("html_url"),
        }
