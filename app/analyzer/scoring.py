from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models import RepositorySnapshot


@dataclass(frozen=True)
class ScoreResult:
    score: int
    status: str
    dimensions: dict[str, int] = field(default_factory=dict)
    risks: list[dict[str, str]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    @classmethod
    def for_score(cls, score: int) -> "ScoreResult":
        clamped_score = _clamp(score)
        return cls(
            score=clamped_score,
            status=_status(clamped_score),
            dimensions={},
            risks=[],
            recommendations=[],
        )


def score_repository(snapshot: RepositorySnapshot, now: datetime | None = None) -> ScoreResult:
    current_time = _as_utc(now or datetime.now(timezone.utc))
    dimensions = {
        "活跃维护": _activity_dimension(snapshot, current_time),
        "社区规范": _community_dimension(snapshot),
        "协作健康": _collaboration_dimension(snapshot),
        "项目成熟度": _maturity_dimension(snapshot),
        "代码组成": _composition_dimension(snapshot),
    }
    risks = _risks(snapshot)
    raw_score = _weighted_total(dimensions) - min(5, len(risks) * 2)
    score = _apply_critical_cap(_clamp(round(raw_score)), risks)
    return ScoreResult(
        score=score,
        status=_status(score),
        dimensions=dimensions,
        risks=risks,
        recommendations=_recommendations(snapshot, risks),
    )


def _weighted_total(dimensions: dict[str, int]) -> float:
    return (
        dimensions["活跃维护"] * 0.30
        + dimensions["社区规范"] * 0.25
        + dimensions["协作健康"] * 0.15
        + dimensions["项目成熟度"] * 0.15
        + dimensions["代码组成"] * 0.10
    )


def _activity_dimension(snapshot: RepositorySnapshot, now: datetime) -> int:
    activity = snapshot.activity
    score = 0
    score += 40 if activity.commits_30d_count >= 10 else activity.commits_30d_count * 4
    score += 35 if activity.commits_90d_count >= 25 else int(activity.commits_90d_count * 1.4)
    score += _freshness_points(snapshot.repo.pushed_at, now, full_days=30, partial_days=90, full=10, partial=5)
    score += _freshness_points(
        activity.latest_release_at,
        now,
        full_days=180,
        partial_days=365,
        full=15,
        partial=8,
    )
    return _clamp(score)


def _community_dimension(snapshot: RepositorySnapshot) -> int:
    files = snapshot.community.files
    score = 0
    score += 25 if files.get("readme") else 0
    score += 25 if files.get("license") or snapshot.repo.license_spdx else 0
    score += 14 if files.get("contributing") else 0
    score += 10 if files.get("code_of_conduct") else 0
    score += 10 if _has_security_policy(files) else 0
    score += 8 if _has_issue_template(files) else 0
    score += 8 if _has_pull_request_template(files) else 0
    return _clamp(score)


def _collaboration_dimension(snapshot: RepositorySnapshot) -> int:
    score = 100
    if snapshot.repo.open_issues > 200:
        score -= 45
    elif snapshot.repo.open_issues > 100:
        score -= 25
    elif snapshot.repo.open_issues > 50:
        score -= 10

    if snapshot.activity.open_pulls_count > 50:
        score -= 45
    elif snapshot.activity.open_pulls_count > 20:
        score -= 20
    elif snapshot.activity.open_pulls_count > 10:
        score -= 10

    if snapshot.activity.contributors_count == 0:
        score -= 10
    return _clamp(score)


def _maturity_dimension(snapshot: RepositorySnapshot) -> int:
    score = 0
    score += 30 if snapshot.repo.stars >= 50 else 15 if snapshot.repo.stars > 0 else 0
    score += 25 if snapshot.repo.forks >= 10 else 12 if snapshot.repo.forks > 0 else 0
    score += 25 if snapshot.activity.contributors_count >= 3 else 10 if snapshot.activity.contributors_count > 0 else 0
    score += 20 if snapshot.activity.releases_count > 0 else 0
    return _clamp(score)


def _composition_dimension(snapshot: RepositorySnapshot) -> int:
    if not snapshot.languages:
        return 0
    if len(snapshot.languages) >= 2:
        return 100
    return 85


def _risks(snapshot: RepositorySnapshot) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    files = snapshot.community.files

    if snapshot.repo.archived:
        risks.append({"code": "archived", "level": "critical", "message": "仓库已归档，后续维护可能停止。"})
    if snapshot.repo.disabled:
        risks.append({"code": "disabled", "level": "critical", "message": "仓库已禁用，需要确认是否仍可使用。"})
    if not snapshot.repo.license_spdx and not files.get("license"):
        risks.append({"code": "missing_license", "level": "warning", "message": "仓库缺少许可证信息。"})
    if not files.get("readme"):
        risks.append({"code": "missing_readme", "level": "warning", "message": "仓库缺少 README。"})
    if snapshot.activity.commits_90d_count == 0:
        risks.append({"code": "inactive", "level": "critical", "message": "仓库近 90 天没有检测到提交。"})
    elif snapshot.activity.commits_30d_count == 0:
        risks.append({"code": "no_recent_commits", "level": "warning", "message": "仓库近 30 天没有检测到提交。"})
    if snapshot.repo.open_issues > 100:
        risks.append({"code": "issue_backlog", "level": "warning", "message": "Open issues 数量较高，可能存在处理积压。"})
    if snapshot.activity.open_pulls_count > 20:
        risks.append({"code": "pull_request_backlog", "level": "warning", "message": "Open pull requests 数量较高，可能存在合并积压。"})
    if snapshot.partial_errors:
        risks.append({"code": "partial_data", "level": "warning", "message": "部分 GitHub 数据获取失败，评分可能不完整。"})
    return risks


def _recommendations(snapshot: RepositorySnapshot, risks: list[dict[str, str]]) -> list[str]:
    recommendations = [_recommendation_for_risk(risk["code"]) for risk in risks]
    files = snapshot.community.files

    if not files.get("contributing"):
        recommendations.append("补充 CONTRIBUTING.md，说明贡献流程。")
    if snapshot.activity.releases_count == 0:
        recommendations.append("补充 Release 或版本说明，方便评估维护节奏。")
    if not _has_security_policy(files):
        recommendations.append("补充安全策略，方便用户报告漏洞。")
    if not _has_issue_template(files):
        recommendations.append("补充 Issue Template，规范问题反馈信息。")
    if not _has_pull_request_template(files):
        recommendations.append("补充 PR Template，规范代码变更说明。")

    return list(dict.fromkeys(item for item in recommendations if item))


def _recommendation_for_risk(code: str) -> str:
    messages = {
        "archived": "确认归档仓库是否仍适合作为依赖或参考。",
        "disabled": "确认仓库禁用原因，并避免继续依赖不可访问项目。",
        "missing_license": "补充许可证文件，明确代码使用边界。",
        "missing_readme": "补充 README，说明项目用途、安装方式和维护状态。",
        "inactive": "恢复维护节奏，或在 README 中说明项目当前状态。",
        "no_recent_commits": "关注近期维护节奏，确认 30 天无提交是否符合项目预期。",
        "issue_backlog": "清理或分流长期未处理的 issues。",
        "pull_request_backlog": "定期处理 open pull requests，降低协作积压。",
        "partial_data": "稍后重试分析，确认缺失数据不会影响判断。",
    }
    return messages.get(code, "")


def _status(score: int) -> str:
    if score >= 85:
        return "优秀"
    if score >= 70:
        return "良好"
    if score >= 55:
        return "一般"
    if score >= 40:
        return "风险"
    return "高风险"


def _clamp(score: int | float) -> int:
    return max(0, min(100, int(score)))


def _apply_critical_cap(score: int, risks: list[dict[str, str]]) -> int:
    critical_codes = {"archived", "disabled", "inactive"}
    if any(risk["code"] in critical_codes for risk in risks):
        return min(score, 54)
    return score


def _freshness_points(
    value: str | None,
    now: datetime,
    *,
    full_days: int,
    partial_days: int,
    full: int,
    partial: int,
) -> int:
    timestamp = _parse_github_datetime(value)
    if timestamp is None:
        return 0
    age_days = (_as_utc(now) - timestamp).total_seconds() / 86400
    if age_days < 0:
        return full
    if age_days <= full_days:
        return full
    if age_days <= partial_days:
        return partial
    return 0


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


def _has_issue_template(files: dict[str, bool]) -> bool:
    return bool(files.get("issue_template") or files.get("issue_template_config"))


def _has_pull_request_template(files: dict[str, bool]) -> bool:
    return bool(files.get("pull_request_template") or files.get("pr_template"))


def _has_security_policy(files: dict[str, bool]) -> bool:
    return bool(files.get("security") or files.get("security_policy") or files.get("security_policy_file"))
