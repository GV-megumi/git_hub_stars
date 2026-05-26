from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.errors import GithubApiError, NotFoundError, PermissionRequiredError
from app.github.client import GithubClient
from app.github.url_parser import RepoRef
from app.models import ActivityInfo, CommunityInfo, RepoInfo, RepositorySnapshot


def collect_repository_snapshot(
    client: GithubClient,
    ref: RepoRef,
    now: datetime | None = None,
) -> RepositorySnapshot:
    current_time = _as_utc(now or datetime.now(timezone.utc))
    commits_since = current_time - timedelta(days=90)
    partial_errors: list[dict[str, Any]] = []
    base_path = f"/repos/{ref.owner}/{ref.repo}"
    repo = client.get_json(base_path)
    languages_raw = client.get_json(f"{base_path}/languages")
    community_raw = _safe_get(client, f"{base_path}/community/profile", default={}, partial_errors=partial_errors)
    releases = _safe_get(
        client,
        f"{base_path}/releases",
        default=[],
        partial_errors=partial_errors,
        params={"per_page": 10},
    )
    contributors = _safe_get(
        client,
        f"{base_path}/contributors",
        default=[],
        partial_errors=partial_errors,
        params={"per_page": 100},
    )
    commits = _safe_get(
        client,
        f"{base_path}/commits",
        default=[],
        partial_errors=partial_errors,
        params={"per_page": 100, "since": _format_github_datetime(commits_since)},
    )
    pulls = _safe_get(
        client,
        f"{base_path}/pulls",
        default=[],
        partial_errors=partial_errors,
        params={"state": "open", "per_page": 100},
    )

    return RepositorySnapshot(
        repo=_build_repo_info(repo),
        languages=_language_percentages(languages_raw),
        community=_build_community_info(community_raw),
        activity=_build_activity_info(
            commits=commits,
            contributors=contributors,
            releases=releases,
            pulls=pulls,
            now=current_time,
        ),
        partial_errors=partial_errors,
    )


def _safe_get(
    client: GithubClient,
    path: str,
    default: Any,
    partial_errors: list[dict[str, Any]],
    params: dict[str, Any] | None = None,
) -> Any:
    try:
        return client.get_json(path, params=params)
    except (GithubApiError, NotFoundError, PermissionRequiredError) as exc:
        error = exc.to_dict()
        error["path"] = path
        error["code"] = exc.code
        partial_errors.append(error)
        return default


def _build_repo_info(repo: dict[str, Any]) -> RepoInfo:
    return RepoInfo(
        full_name=repo["full_name"],
        description=repo.get("description"),
        stars=repo.get("stargazers_count", 0),
        forks=repo.get("forks_count", 0),
        watchers=repo.get("subscribers_count", repo.get("watchers_count", 0)),
        open_issues=repo.get("open_issues_count", 0),
        default_branch=repo.get("default_branch", "main"),
        license_spdx=(repo.get("license") or {}).get("spdx_id"),
        archived=repo.get("archived", False),
        disabled=repo.get("disabled", False),
        fork=repo.get("fork", False),
        pushed_at=repo.get("pushed_at"),
        updated_at=repo.get("updated_at"),
        created_at=repo.get("created_at"),
        size_kb=repo.get("size", 0),
    )


def _language_percentages(languages_raw: dict[str, int]) -> dict[str, float]:
    total_bytes = sum(languages_raw.values())
    if total_bytes <= 0:
        return {}
    return {
        language: round((byte_count / total_bytes) * 100, 1)
        for language, byte_count in languages_raw.items()
        if byte_count > 0
    }


def _build_community_info(community_raw: dict[str, Any]) -> CommunityInfo:
    files = community_raw.get("files") or {}
    return CommunityInfo(
        health_percentage=community_raw.get("health_percentage"),
        files={name: bool(value) for name, value in files.items()},
    )


def _build_activity_info(
    commits: list[dict[str, Any]],
    contributors: list[dict[str, Any]],
    releases: list[dict[str, Any]],
    pulls: list[dict[str, Any]],
    now: datetime,
) -> ActivityInfo:
    latest_release_at = _latest_release_at(releases)
    commits_90d_count = _count_commits_since(commits, now - timedelta(days=90))
    return ActivityInfo(
        recent_commits_count=commits_90d_count,
        commits_30d_count=_count_commits_since(commits, now - timedelta(days=30)),
        commits_90d_count=commits_90d_count,
        contributors_count=len(contributors),
        releases_count=len(releases),
        latest_release_at=latest_release_at,
        open_pulls_count=len(pulls),
    )


def _count_commits_since(commits: list[dict[str, Any]], threshold: datetime) -> int:
    return sum(
        1
        for commit in commits
        if (commit_time := _commit_datetime(commit)) is not None and commit_time >= threshold
    )


def _commit_datetime(commit: dict[str, Any]) -> datetime | None:
    commit_data = commit.get("commit") or {}
    author_date = (commit_data.get("author") or {}).get("date")
    committer_date = (commit_data.get("committer") or {}).get("date")
    return _parse_github_datetime(committer_date) or _parse_github_datetime(author_date)


def _latest_release_at(releases: list[dict[str, Any]]) -> str | None:
    latest_timestamp: datetime | None = None
    latest_value: str | None = None
    for release in releases:
        value = release.get("published_at") or release.get("created_at")
        timestamp = _parse_github_datetime(value)
        if timestamp is not None and (latest_timestamp is None or timestamp > latest_timestamp):
            latest_timestamp = timestamp
            latest_value = value
    return latest_value


def _parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_github_datetime(value: datetime) -> str:
    value = _as_utc(value).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")
