from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import asdict, replace

from app.analyzer.scoring import ScoreResult, score_repository
from app.models import ActivityInfo, CommunityInfo, RepoInfo, RepositorySnapshot


FIXED_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)


def make_snapshot(
    *,
    repo_overrides: dict | None = None,
    community_files: dict[str, bool] | None = None,
    activity_overrides: dict | None = None,
    languages: dict[str, float] | None = None,
    partial_errors: list[dict[str, object]] | None = None,
) -> RepositorySnapshot:
    repo = RepoInfo(
        full_name="owner/repo",
        description="Example project",
        stars=150,
        forks=25,
        watchers=10,
        open_issues=8,
        default_branch="main",
        license_spdx="MIT",
        archived=False,
        disabled=False,
        fork=False,
        pushed_at="2026-05-20T00:00:00Z",
        updated_at="2026-05-21T00:00:00Z",
        created_at="2025-01-01T00:00:00Z",
        size_kb=2048,
    )
    if repo_overrides:
        repo = replace(repo, **repo_overrides)

    activity = ActivityInfo(
        recent_commits_count=20,
        commits_30d_count=8,
        commits_90d_count=20,
        contributors_count=5,
        releases_count=3,
        latest_release_at="2026-05-01T00:00:00Z",
        open_pulls_count=3,
    )
    if activity_overrides:
        activity = replace(activity, **activity_overrides)

    files = {
        "readme": True,
        "license": True,
        "contributing": True,
        "code_of_conduct": True,
        "security": True,
        "issue_template": True,
        "pull_request_template": True,
    }
    if community_files is not None:
        files = community_files

    return RepositorySnapshot(
        repo=repo,
        languages={"Python": 82.0, "HTML": 18.0} if languages is None else languages,
        community=CommunityInfo(health_percentage=90, files=files),
        activity=activity,
        partial_errors=[] if partial_errors is None else partial_errors,
    )


def risk_codes(result: ScoreResult) -> set[str]:
    return {risk["code"] for risk in result.risks}


def test_healthy_repository_scores_good_or_better_and_is_serializable():
    result = score_repository(make_snapshot())

    assert result.score >= 70
    assert result.status in {"良好", "优秀"}
    assert set(result.dimensions) == {"活跃维护", "社区规范", "协作健康", "项目成熟度", "代码组成"}
    assert all(0 <= score <= 100 for score in result.dimensions.values())
    json.dumps(asdict(result), ensure_ascii=False)


def test_archived_repository_gets_archived_risk_and_lower_score():
    result = score_repository(make_snapshot(repo_overrides={"archived": True}))

    assert result.score < score_repository(make_snapshot()).score
    assert "archived" in risk_codes(result)
    assert any("归档" in item["message"] for item in result.risks)


def test_archived_repository_is_capped_at_risk_status():
    result = score_repository(make_snapshot(repo_overrides={"archived": True}), now=FIXED_NOW)

    assert result.score <= 54
    assert result.status in {"风险", "高风险"}


def test_disabled_repository_gets_disabled_risk_and_recommendation():
    result = score_repository(make_snapshot(repo_overrides={"disabled": True}))

    assert "disabled" in risk_codes(result)
    assert any("禁用" in item["message"] for item in result.risks)
    assert any("禁用" in item for item in result.recommendations)


def test_disabled_repository_is_capped_at_risk_status():
    result = score_repository(make_snapshot(repo_overrides={"disabled": True}), now=FIXED_NOW)

    assert result.score <= 54
    assert result.status in {"风险", "高风险"}


def test_missing_license_and_readme_create_risks_and_reduce_community_dimension():
    result = score_repository(
        make_snapshot(
            repo_overrides={"license_spdx": None},
            community_files={
                "readme": False,
                "license": False,
                "contributing": True,
                "code_of_conduct": True,
                "security": True,
            },
        )
    )

    assert {"missing_license", "missing_readme"} <= risk_codes(result)
    assert result.dimensions["社区规范"] < 100
    assert any("README" in item for item in result.recommendations)
    assert any("许可证" in item for item in result.recommendations)


def test_issue_and_pull_request_templates_increase_community_dimension():
    without_templates = score_repository(
        make_snapshot(
            community_files={
                "readme": True,
                "license": True,
                "contributing": True,
                "code_of_conduct": True,
                "security": True,
                "issue_template": False,
                "pull_request_template": False,
            }
        )
    )
    with_templates = score_repository(
        make_snapshot(
            community_files={
                "readme": True,
                "license": True,
                "contributing": True,
                "code_of_conduct": True,
                "security": True,
                "issue_template_config": True,
                "pr_template": True,
            }
        )
    )

    assert without_templates.dimensions["社区规范"] < with_templates.dimensions["社区规范"]
    assert with_templates.dimensions["社区规范"] == 100
    assert any("Issue" in item for item in without_templates.recommendations)
    assert any("PR" in item for item in without_templates.recommendations)


def test_security_policy_aliases_count_as_security_coverage():
    with_security_policy = score_repository(
        make_snapshot(
            community_files={
                "readme": True,
                "license": True,
                "contributing": True,
                "code_of_conduct": True,
                "security": False,
                "security_policy": True,
                "issue_template": True,
                "pull_request_template": True,
            }
        )
    )
    with_security_policy_file = score_repository(
        make_snapshot(
            community_files={
                "readme": True,
                "license": True,
                "contributing": True,
                "code_of_conduct": True,
                "security": False,
                "security_policy_file": True,
                "issue_template": True,
                "pull_request_template": True,
            }
        )
    )

    assert with_security_policy.dimensions["社区规范"] == 100
    assert with_security_policy_file.dimensions["社区规范"] == 100
    assert not any("安全策略" in item for item in with_security_policy.recommendations)
    assert not any("安全策略" in item for item in with_security_policy_file.recommendations)


def test_inactive_repository_with_backlog_is_high_risk():
    result = score_repository(
        make_snapshot(
            repo_overrides={
                "stars": 0,
                "forks": 0,
                "open_issues": 250,
                "license_spdx": None,
                "pushed_at": "2024-01-01T00:00:00Z",
            },
            community_files={"readme": False, "license": False},
            activity_overrides={
                "recent_commits_count": 0,
                "commits_30d_count": 0,
                "commits_90d_count": 0,
                "contributors_count": 0,
                "releases_count": 0,
                "latest_release_at": None,
                "open_pulls_count": 80,
            },
            languages={},
        )
    )

    assert result.score <= 39
    assert result.status == "高风险"
    assert {"inactive", "issue_backlog", "pull_request_backlog"} <= risk_codes(result)


def test_otherwise_healthy_inactive_repository_is_capped_at_risk_status():
    result = score_repository(
        make_snapshot(
            activity_overrides={
                "recent_commits_count": 0,
                "commits_30d_count": 0,
                "commits_90d_count": 0,
            }
        ),
        now=FIXED_NOW,
    )

    assert result.score <= 54
    assert result.status in {"风险", "高风险"}
    assert "inactive" in risk_codes(result)


def test_no_recent_commits_creates_warning_when_90_day_activity_exists():
    result = score_repository(
        make_snapshot(
            activity_overrides={
                "commits_30d_count": 0,
                "commits_90d_count": 4,
                "recent_commits_count": 4,
            }
        )
    )

    assert "no_recent_commits" in risk_codes(result)
    assert "inactive" not in risk_codes(result)
    assert any("近期" in item or "30" in item for item in result.recommendations)


def test_recent_push_and_release_score_higher_than_old_dates():
    recent = score_repository(
        make_snapshot(
            repo_overrides={"pushed_at": "2026-05-20T00:00:00Z"},
            activity_overrides={"latest_release_at": "2026-05-01T00:00:00Z"},
        ),
        now=FIXED_NOW,
    )
    old = score_repository(
        make_snapshot(
            repo_overrides={"pushed_at": "2025-01-01T00:00:00Z"},
            activity_overrides={"latest_release_at": "2024-01-01T00:00:00Z"},
        ),
        now=FIXED_NOW,
    )

    assert recent.dimensions["活跃维护"] > old.dimensions["活跃维护"]
    assert recent.score > old.score


def test_partial_errors_create_risk_without_breaking_scoring():
    result = score_repository(
        make_snapshot(
            partial_errors=[
                {
                    "path": "/repos/owner/repo/releases",
                    "code": "github_api_error",
                    "message": "GitHub API request failed.",
                }
            ]
        )
    )

    assert "partial_data" in risk_codes(result)
    assert 0 <= result.score <= 100
    assert any("部分" in item["message"] for item in result.risks)


def test_status_segments_are_inclusive_at_lower_bounds():
    assert ScoreResult.for_score(85).status == "优秀"
    assert ScoreResult.for_score(70).status == "良好"
    assert ScoreResult.for_score(55).status == "一般"
    assert ScoreResult.for_score(40).status == "风险"
    assert ScoreResult.for_score(39).status == "高风险"


def test_score_is_clamped_to_zero_and_one_hundred():
    assert ScoreResult.for_score(250).score == 100
    assert ScoreResult.for_score(-10).score == 0
