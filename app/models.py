from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RepoInfo:
    full_name: str
    description: str | None
    stars: int
    forks: int
    watchers: int
    open_issues: int
    default_branch: str
    license_spdx: str | None
    archived: bool
    disabled: bool
    fork: bool
    pushed_at: str | None
    updated_at: str | None
    created_at: str | None
    size_kb: int


@dataclass(frozen=True)
class CommunityInfo:
    health_percentage: int | None
    files: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class ActivityInfo:
    recent_commits_count: int
    commits_30d_count: int
    commits_90d_count: int
    contributors_count: int
    releases_count: int
    latest_release_at: str | None
    open_pulls_count: int
    releases_count_is_sampled: bool = True


@dataclass(frozen=True)
class RepositorySnapshot:
    repo: RepoInfo
    languages: dict[str, float]
    community: CommunityInfo
    activity: ActivityInfo
    partial_errors: list[dict[str, object]] = field(default_factory=list)
