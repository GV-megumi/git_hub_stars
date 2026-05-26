# Github Repo Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python + HTML web app that analyzes public Github repositories without login, supports GitHub App installation authorization for private repositories, shows system health scoring first, and optionally runs AI agent analysis with Github API tools plus Tavily for public repositories.

**Architecture:** Use Flask as the web/API server, with focused service modules for configuration, Github API access, GitHub App authorization, deterministic health scoring, and AI agent orchestration. The frontend is a single server-rendered HTML page with static JavaScript and Chart.js, calling JSON endpoints for system analysis, authorization status, and optional agent analysis.

**Tech Stack:** Python 3.11, Flask, requests, python-dotenv, PyJWT, cryptography, pydantic/dataclasses, OpenAI-compatible chat API, pytest, requests-mock, HTML/CSS/JavaScript, Chart.js.

---

## Source Spec

- `docs/superpowers/specs/2026-05-26-github-repo-health-design.md`

## File Structure

- `app/__init__.py`: Flask app factory and route registration.
- `app/config.py`: `.env` loading and typed application settings.
- `app/errors.py`: shared exception classes and API error serialization.
- `app/models.py`: dataclasses for repository metrics, scoring, agent tools, and API responses.
- `app/routes.py`: Flask HTTP routes for page, health, system analysis, GitHub App installation status, and agent analysis.
- `app/github/url_parser.py`: strict Github repository URL parsing.
- `app/github/client.py`: Github REST client with anonymous public mode and installation-token mode.
- `app/github/app_auth.py`: GitHub App JWT creation and installation token exchange.
- `app/analyzer/collector.py`: orchestration layer that fetches Github data for system scoring.
- `app/analyzer/scoring.py`: deterministic score calculation and risk recommendations.
- `app/analyzer/normalizers.py`: small helpers for date, language, issue, release, and permission summaries.
- `app/agent/tools.py`: controlled read-only Github API tools exposed to the agent.
- `app/agent/llm.py`: OpenAI-compatible model client wrapper.
- `app/agent/tavily.py`: Tavily search/extract wrapper for public repository external evidence.
- `app/agent/service.py`: agent analysis orchestration and output validation.
- `templates/index.html`: single-page user interface.
- `static/css/styles.css`: responsive UI styling.
- `static/js/app.js`: browser state, API calls, rendering, and charts.
- `tests/`: pytest suite mirroring the modules above.
- `README.md`: setup, configuration, run, test, GitHub App, and agent notes.
- `.env.example`: safe example environment file.
- `.gitignore`: Python, local environment, secret, and generated file ignores.
- `requirements.txt`: runtime and test dependencies.
- `AGENTS.md`: repo-specific instructions for future agents.

## Task Breakdown

### Task 1: Project Skeleton and Configuration

**Files:**
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/errors.py`
- Create: `tests/test_config.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Write failing config tests**

Create `tests/test_config.py`:

```python
import pytest

from app.config import Settings


def test_settings_defaults_allow_public_mode(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("MODEL_BASE_URL", raising=False)

    settings = Settings.from_env()

    assert settings.github_app_configured is False
    assert settings.agent_configured is False
    assert settings.flask_secret_key


def test_agent_config_requires_all_model_values(monkeypatch):
    monkeypatch.setenv("MODEL_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("MODEL_API_KEY", "key")
    monkeypatch.setenv("MODEL_NAME", "model-a")

    settings = Settings.from_env()

    assert settings.agent_configured is True
```

- [ ] **Step 2: Run config tests and verify they fail**

Run: `pytest tests/test_config.py -v`

Expected: import failure for `app.config` because the module does not exist.

- [ ] **Step 3: Add config and app factory**

Create `app/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


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
    def from_env(cls) -> "Settings":
        load_dotenv()
        private_key = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
        return cls(
            flask_env=os.getenv("FLASK_ENV", "development"),
            flask_secret_key=os.getenv("FLASK_SECRET_KEY", "dev-only-change-me"),
            github_app_id=os.getenv("GITHUB_APP_ID"),
            github_app_slug=os.getenv("GITHUB_APP_SLUG"),
            github_app_private_key_path=Path(private_key) if private_key else None,
            github_app_setup_url=os.getenv("GITHUB_APP_SETUP_URL"),
            tavily_api_key=os.getenv("TAVILY_API_KEY"),
            model_base_url=os.getenv("MODEL_BASE_URL"),
            model_api_key=os.getenv("MODEL_API_KEY"),
            model_name=os.getenv("MODEL_NAME"),
            github_api_base_url=os.getenv("GITHUB_API_BASE_URL", "https://api.github.com"),
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
```

Create `app/errors.py`:

```python
from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}


class ValidationError(AppError):
    status_code = 400
    code = "validation_error"


class GithubApiError(AppError):
    status_code = 502
    code = "github_api_error"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class PermissionRequiredError(AppError):
    status_code = 403
    code = "permission_required"
```

Create `app/__init__.py`:

```python
from __future__ import annotations

from flask import Flask, jsonify

from app.config import Settings
from app.errors import AppError


def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config["APP_SETTINGS"] = settings or Settings.from_env()
    app.secret_key = app.config["APP_SETTINGS"].flask_secret_key

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        return jsonify(error.to_dict()), error.status_code

    from app.routes import bp

    app.register_blueprint(bp)
    return app
```

- [ ] **Step 4: Add placeholder routes required by app factory**

Create `app/routes.py`:

```python
from __future__ import annotations

from flask import Blueprint, jsonify

bp = Blueprint("main", __name__)


@bp.get("/api/health")
def health():
    return jsonify({"status": "ok"})
```

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_config.py -v`

Expected: all tests pass.

Commit:

```powershell
git add app tests requirements.txt
git commit -m "feat: add app skeleton and configuration"
```

### Task 2: Github URL Parsing

**Files:**
- Create: `app/github/__init__.py`
- Create: `app/github/url_parser.py`
- Create: `tests/test_url_parser.py`

- [ ] **Step 1: Write URL parser tests**

Create `tests/test_url_parser.py`:

```python
import pytest

from app.errors import ValidationError
from app.github.url_parser import parse_github_repo_url


@pytest.mark.parametrize(
    ("url", "owner", "repo"),
    [
        ("https://github.com/fastapi/fastapi", "fastapi", "fastapi"),
        ("https://github.com/pallets/flask.git", "pallets", "flask"),
        ("https://www.github.com/psf/requests/", "psf", "requests"),
    ],
)
def test_parse_valid_github_url(url, owner, repo):
    result = parse_github_repo_url(url)

    assert result.owner == owner
    assert result.repo == repo
    assert result.full_name == f"{owner}/{repo}"


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://gitlab.com/a/b",
        "https://github.com/a",
        "https://github.com/a/b/issues",
        "not-a-url",
    ],
)
def test_reject_invalid_repo_url(url):
    with pytest.raises(ValidationError):
        parse_github_repo_url(url)
```

- [ ] **Step 2: Run parser tests and verify failure**

Run: `pytest tests/test_url_parser.py -v`

Expected: import failure for `app.github.url_parser`.

- [ ] **Step 3: Implement parser**

Create `app/github/__init__.py`:

```python
"""Github integration package."""
```

Create `app/github/url_parser.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.errors import ValidationError


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


def parse_github_repo_url(raw_url: str) -> RepoRef:
    parsed = urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValidationError("请输入 https://github.com/{owner}/{repo} 格式的仓库地址。")
    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise ValidationError("只支持 github.com 仓库地址。")

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ValidationError("请输入仓库根地址，不要包含 issues、pulls 或其他子路径。")

    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise ValidationError("仓库地址缺少 owner 或 repo。")

    return RepoRef(owner=owner, repo=repo)
```

- [ ] **Step 4: Run parser tests and commit**

Run: `pytest tests/test_url_parser.py -v`

Expected: all parser tests pass.

Commit:

```powershell
git add app/github tests/test_url_parser.py
git commit -m "feat: parse github repository urls"
```

### Task 3: Github REST Client

**Files:**
- Create: `app/github/client.py`
- Create: `tests/test_github_client.py`

- [ ] **Step 1: Write Github client tests**

Create `tests/test_github_client.py`:

```python
import pytest

from app.errors import NotFoundError, PermissionRequiredError
from app.github.client import GithubClient


def test_get_repo_summary_uses_public_api(requests_mock):
    requests_mock.get(
        "https://api.github.com/repos/fastapi/fastapi",
        json={"full_name": "fastapi/fastapi", "stargazers_count": 1},
    )
    client = GithubClient()

    data = client.get_json("/repos/fastapi/fastapi")

    assert data["full_name"] == "fastapi/fastapi"
    assert requests_mock.last_request.headers["Accept"] == "application/vnd.github+json"


def test_404_raises_not_found(requests_mock):
    requests_mock.get("https://api.github.com/repos/a/missing", status_code=404, json={})
    client = GithubClient()

    with pytest.raises(NotFoundError):
        client.get_json("/repos/a/missing")


def test_403_raises_permission_required(requests_mock):
    requests_mock.get("https://api.github.com/repos/a/private", status_code=403, json={})
    client = GithubClient()

    with pytest.raises(PermissionRequiredError):
        client.get_json("/repos/a/private")
```

- [ ] **Step 2: Run client tests and verify failure**

Run: `pytest tests/test_github_client.py -v`

Expected: import failure for `app.github.client`.

- [ ] **Step 3: Implement client**

Create `app/github/client.py`:

```python
from __future__ import annotations

from typing import Any

import requests

from app.errors import GithubApiError, NotFoundError, PermissionRequiredError


class GithubClient:
    def __init__(self, base_url: str = "https://api.github.com", token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = requests.get(
            f"{self.base_url}{path}",
            params=params,
            headers=self._headers(),
            timeout=20,
        )
        if response.status_code == 404:
            raise NotFoundError("仓库不存在，或当前授权范围无法访问该仓库。")
        if response.status_code in {401, 403}:
            raise PermissionRequiredError("Github API 权限不足或请求频率受限。")
        if response.status_code >= 400:
            raise GithubApiError(f"Github API 请求失败：HTTP {response.status_code}")
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
```

- [ ] **Step 4: Run client tests and commit**

Run: `pytest tests/test_github_client.py -v`

Expected: all client tests pass.

Commit:

```powershell
git add app/github/client.py tests/test_github_client.py
git commit -m "feat: add github rest client"
```

### Task 4: System Data Collection

**Files:**
- Create: `app/models.py`
- Create: `app/analyzer/__init__.py`
- Create: `app/analyzer/collector.py`
- Create: `tests/test_collector.py`

- [ ] **Step 1: Write collector tests with fake client**

Create `tests/test_collector.py`:

```python
from app.analyzer.collector import collect_repository_snapshot
from app.github.url_parser import RepoRef


class FakeClient:
    def get_json(self, path, params=None):
        fixtures = {
            "/repos/owner/repo": {
                "full_name": "owner/repo",
                "description": "Example",
                "stargazers_count": 10,
                "forks_count": 2,
                "subscribers_count": 3,
                "open_issues_count": 4,
                "default_branch": "main",
                "license": {"spdx_id": "MIT"},
                "archived": False,
                "disabled": False,
                "fork": False,
                "pushed_at": "2026-05-20T00:00:00Z",
                "updated_at": "2026-05-21T00:00:00Z",
                "created_at": "2025-01-01T00:00:00Z",
                "size": 123,
            },
            "/repos/owner/repo/languages": {"Python": 900, "HTML": 100},
            "/repos/owner/repo/community/profile": {
                "health_percentage": 80,
                "files": {"readme": {"url": "x"}, "license": {"url": "y"}},
            },
            "/repos/owner/repo/releases": [{"tag_name": "v1.0.0", "published_at": "2026-05-01T00:00:00Z"}],
            "/repos/owner/repo/contributors": [{"login": "alice"}, {"login": "bob"}],
            "/repos/owner/repo/commits": [{"sha": "1"}, {"sha": "2"}],
            "/repos/owner/repo/pulls": [{"number": 5}],
        }
        return fixtures[path]


def test_collect_repository_snapshot_normalizes_core_fields():
    snapshot = collect_repository_snapshot(FakeClient(), RepoRef("owner", "repo"))

    assert snapshot.repo.full_name == "owner/repo"
    assert snapshot.languages["Python"] == 90.0
    assert snapshot.community.health_percentage == 80
    assert snapshot.activity.recent_commits_count == 2
    assert snapshot.activity.contributors_count == 2
    assert snapshot.activity.open_pulls_count == 1
```

- [ ] **Step 2: Run collector tests and verify failure**

Run: `pytest tests/test_collector.py -v`

Expected: import failure for `app.analyzer.collector`.

- [ ] **Step 3: Implement collector models and orchestration**

Create `app/models.py`:

```python
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
    contributors_count: int
    releases_count: int
    latest_release_at: str | None
    open_pulls_count: int


@dataclass(frozen=True)
class RepositorySnapshot:
    repo: RepoInfo
    languages: dict[str, float]
    community: CommunityInfo
    activity: ActivityInfo
```

Create `app/analyzer/__init__.py`:

```python
"""Repository health analysis package."""
```

Create `app/analyzer/collector.py`:

```python
from __future__ import annotations

from app.github.client import GithubClient
from app.github.url_parser import RepoRef
from app.models import ActivityInfo, CommunityInfo, RepoInfo, RepositorySnapshot


def collect_repository_snapshot(client: GithubClient, ref: RepoRef) -> RepositorySnapshot:
    base = f"/repos/{ref.owner}/{ref.repo}"
    repo = client.get_json(base)
    languages_raw = client.get_json(f"{base}/languages")
    community_raw = _safe_get(client, f"{base}/community/profile", default={})
    releases = _safe_get(client, f"{base}/releases", default=[], params={"per_page": 10})
    contributors = _safe_get(client, f"{base}/contributors", default=[], params={"per_page": 100})
    commits = _safe_get(client, f"{base}/commits", default=[], params={"per_page": 100})
    pulls = _safe_get(client, f"{base}/pulls", default=[], params={"state": "open", "per_page": 100})

    return RepositorySnapshot(
        repo=RepoInfo(
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
        ),
        languages=_language_percentages(languages_raw),
        community=_community_info(community_raw),
        activity=ActivityInfo(
            recent_commits_count=len(commits),
            contributors_count=len(contributors),
            releases_count=len(releases),
            latest_release_at=releases[0].get("published_at") if releases else None,
            open_pulls_count=len(pulls),
        ),
    )


def _safe_get(client: GithubClient, path: str, default, params: dict | None = None):
    try:
        return client.get_json(path, params=params)
    except Exception:
        return default


def _language_percentages(raw: dict[str, int]) -> dict[str, float]:
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {name: round(bytes_count / total * 100, 2) for name, bytes_count in raw.items()}


def _community_info(raw: dict) -> CommunityInfo:
    files = raw.get("files") or {}
    return CommunityInfo(
        health_percentage=raw.get("health_percentage"),
        files={name: bool(value) for name, value in files.items()},
    )
```

- [ ] **Step 4: Run collector tests and commit**

Run: `pytest tests/test_collector.py -v`

Expected: all collector tests pass.

Commit:

```powershell
git add app/models.py app/analyzer tests/test_collector.py
git commit -m "feat: collect github repository snapshot"
```

### Task 5: Deterministic System Scoring

**Files:**
- Create: `app/analyzer/scoring.py`
- Create: `tests/test_scoring.py`

- [ ] **Step 1: Write scoring tests**

Create `tests/test_scoring.py`:

```python
from app.analyzer.scoring import score_repository
from app.models import ActivityInfo, CommunityInfo, RepoInfo, RepositorySnapshot


def make_snapshot(**repo_overrides):
    repo = RepoInfo(
        full_name="owner/repo",
        description="Example",
        stars=100,
        forks=10,
        watchers=5,
        open_issues=3,
        default_branch="main",
        license_spdx="MIT",
        archived=False,
        disabled=False,
        fork=False,
        pushed_at="2026-05-20T00:00:00Z",
        updated_at="2026-05-21T00:00:00Z",
        created_at="2025-01-01T00:00:00Z",
        size_kb=100,
    )
    repo = repo.__class__(**{**repo.__dict__, **repo_overrides})
    return RepositorySnapshot(
        repo=repo,
        languages={"Python": 90.0, "HTML": 10.0},
        community=CommunityInfo(health_percentage=80, files={"readme": True, "license": True}),
        activity=ActivityInfo(
            recent_commits_count=20,
            contributors_count=5,
            releases_count=2,
            latest_release_at="2026-05-01T00:00:00Z",
            open_pulls_count=1,
        ),
    )


def test_healthy_repository_scores_good_or_better():
    result = score_repository(make_snapshot())

    assert result.score >= 70
    assert result.status in {"良好", "优秀"}


def test_archived_repository_gets_risk_warning():
    result = score_repository(make_snapshot(archived=True))

    assert result.score < 85
    assert any(item["code"] == "archived" for item in result.risks)
```

- [ ] **Step 2: Run scoring tests and verify failure**

Run: `pytest tests/test_scoring.py -v`

Expected: import failure for `app.analyzer.scoring`.

- [ ] **Step 3: Implement scoring**

Create `app/analyzer/scoring.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from app.models import RepositorySnapshot


@dataclass(frozen=True)
class ScoreResult:
    score: int
    status: str
    dimensions: dict[str, int]
    risks: list[dict[str, str]]
    recommendations: list[str]


def score_repository(snapshot: RepositorySnapshot) -> ScoreResult:
    dimensions = {
        "活跃维护": _cap(snapshot.activity.recent_commits_count, 30),
        "社区规范": _community_score(snapshot),
        "协作健康": _collaboration_score(snapshot),
        "项目成熟度": _maturity_score(snapshot),
        "代码组成": 10 if snapshot.languages else 0,
    }
    risks = _risks(snapshot)
    raw_score = sum(dimensions.values()) - min(5, len(risks) * 2)
    score = max(0, min(100, raw_score))
    return ScoreResult(
        score=score,
        status=_status(score),
        dimensions=dimensions,
        risks=risks,
        recommendations=_recommendations(snapshot, risks),
    )


def _cap(value: int, maximum: int) -> int:
    return max(0, min(maximum, value))


def _community_score(snapshot: RepositorySnapshot) -> int:
    files = snapshot.community.files
    score = 0
    score += 8 if files.get("readme") else 0
    score += 7 if files.get("license") or snapshot.repo.license_spdx else 0
    score += 4 if files.get("contributing") else 0
    score += 3 if files.get("code_of_conduct") else 0
    score += 3 if files.get("security") else 0
    return min(25, score)


def _collaboration_score(snapshot: RepositorySnapshot) -> int:
    score = 15
    if snapshot.repo.open_issues > 100:
        score -= 5
    if snapshot.activity.open_pulls_count > 50:
        score -= 5
    return max(0, score)


def _maturity_score(snapshot: RepositorySnapshot) -> int:
    score = 0
    score += 5 if snapshot.repo.stars >= 50 else 2 if snapshot.repo.stars > 0 else 0
    score += 4 if snapshot.repo.forks >= 10 else 2 if snapshot.repo.forks > 0 else 0
    score += 3 if snapshot.activity.contributors_count >= 3 else 1
    score += 3 if snapshot.activity.releases_count > 0 else 0
    return min(15, score)


def _risks(snapshot: RepositorySnapshot) -> list[dict[str, str]]:
    risks: list[dict[str, str]] = []
    if snapshot.repo.archived:
        risks.append({"code": "archived", "level": "critical", "message": "仓库已归档。"})
    if snapshot.repo.disabled:
        risks.append({"code": "disabled", "level": "critical", "message": "仓库已禁用。"})
    if not snapshot.repo.license_spdx and not snapshot.community.files.get("license"):
        risks.append({"code": "missing_license", "level": "warning", "message": "仓库缺少许可证信息。"})
    if not snapshot.community.files.get("readme"):
        risks.append({"code": "missing_readme", "level": "warning", "message": "仓库缺少 README。"})
    return risks


def _recommendations(snapshot: RepositorySnapshot, risks: list[dict[str, str]]) -> list[str]:
    recommendations = [risk["message"] for risk in risks]
    if not snapshot.community.files.get("contributing"):
        recommendations.append("补充 CONTRIBUTING.md，说明贡献流程。")
    if snapshot.activity.releases_count == 0:
        recommendations.append("补充 Release 或版本说明，方便评估维护节奏。")
    return recommendations


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
```

- [ ] **Step 4: Run scoring tests and commit**

Run: `pytest tests/test_scoring.py -v`

Expected: all scoring tests pass.

Commit:

```powershell
git add app/analyzer/scoring.py tests/test_scoring.py
git commit -m "feat: add deterministic health scoring"
```

### Task 6: GitHub App Installation Authorization

**Files:**
- Create: `app/github/app_auth.py`
- Create: `tests/test_github_app_auth.py`
- Modify: `app/routes.py`

- [ ] **Step 1: Write GitHub App auth tests**

Create `tests/test_github_app_auth.py`:

```python
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.github.app_auth import GithubAppAuth


def test_build_install_url():
    auth = GithubAppAuth(app_slug="repo-health", app_id="123", private_key_path=Path("missing.pem"))

    assert auth.install_url() == "https://github.com/apps/repo-health/installations/new"


def test_jwt_contains_app_issuer(tmp_path):
    private_pem, public_pem = generate_test_key_pair()
    key = tmp_path / "app.pem"
    key.write_text(private_pem, encoding="utf-8")
    auth = GithubAppAuth(app_slug="repo-health", app_id="123", private_key_path=key)

    token = auth.create_app_jwt()
    payload = jwt.decode(token, public_pem, algorithms=["RS256"], options={"verify_aud": False})

    assert payload["iss"] == "123"


def generate_test_key_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem
```

- [ ] **Step 2: Run auth tests and verify failure**

Run: `pytest tests/test_github_app_auth.py -v`

Expected: import failure for `app.github.app_auth`.

- [ ] **Step 3: Implement GitHub App auth service**

Create `app/github/app_auth.py`:

```python
from __future__ import annotations

import time
from pathlib import Path

import jwt
import requests

from app.errors import GithubApiError


class GithubAppAuth:
    def __init__(self, app_slug: str, app_id: str, private_key_path: Path, api_base_url: str = "https://api.github.com"):
        self.app_slug = app_slug
        self.app_id = app_id
        self.private_key_path = private_key_path
        self.api_base_url = api_base_url.rstrip("/")

    def install_url(self) -> str:
        return f"https://github.com/apps/{self.app_slug}/installations/new"

    def create_app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        private_key = self.private_key_path.read_text(encoding="utf-8")
        return jwt.encode(payload, private_key, algorithm="RS256")

    def create_installation_token(self, installation_id: str, repository: str | None = None) -> dict:
        body = {}
        if repository:
            body["repositories"] = [repository]
        response = requests.post(
            f"{self.api_base_url}/app/installations/{installation_id}/access_tokens",
            json=body,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.create_app_jwt()}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20,
        )
        if response.status_code >= 400:
            raise GithubApiError(f"无法创建 GitHub App installation token：HTTP {response.status_code}")
        return response.json()
```

- [ ] **Step 4: Add installation routes**

Modify `app/routes.py`:

```python
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, redirect, request, session

from app.errors import ValidationError
from app.github.app_auth import GithubAppAuth

bp = Blueprint("main", __name__)


@bp.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@bp.get("/github-app/install")
def github_app_install():
    settings = current_app.config["APP_SETTINGS"]
    if not settings.github_app_configured:
        raise ValidationError("GitHub App 未配置，公开仓库仍可匿名分析。")
    auth = GithubAppAuth(settings.github_app_slug, settings.github_app_id, settings.github_app_private_key_path)
    return redirect(auth.install_url())


@bp.get("/github-app/setup")
def github_app_setup():
    installation_id = request.args.get("installation_id")
    if not installation_id:
        raise ValidationError("GitHub App 安装回调缺少 installation_id。")
    session["github_installation_id"] = installation_id
    return redirect("/")


@bp.post("/github-app/clear")
def github_app_clear():
    session.pop("github_installation_id", None)
    return jsonify({"installed": False})


@bp.get("/api/github-app/session")
def github_app_session():
    return jsonify({"installed": bool(session.get("github_installation_id"))})
```

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_github_app_auth.py tests/test_config.py -v`

Expected: all tests pass.

Commit:

```powershell
git add app/github/app_auth.py app/routes.py tests/test_github_app_auth.py
git commit -m "feat: add github app installation authorization"
```

### Task 7: System Analysis API

**Files:**
- Modify: `app/routes.py`
- Create: `tests/test_routes_analyze.py`

- [ ] **Step 1: Write route tests**

Create `tests/test_routes_analyze.py`:

```python
from app import create_app
from app.config import Settings


def test_analyze_rejects_bad_url():
    app = create_app(Settings.from_env())
    client = app.test_client()

    response = client.post("/api/analyze", json={"url": "bad"})

    assert response.status_code == 400
    assert response.json["error"] == "validation_error"


def test_health_endpoint():
    app = create_app(Settings.from_env())
    client = app.test_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}
```

- [ ] **Step 2: Run route tests**

Run: `pytest tests/test_routes_analyze.py -v`

Expected: bad URL test fails because `/api/analyze` is not implemented.

- [ ] **Step 3: Implement `/api/analyze` route**

Modify `app/routes.py` by adding:

```python
from dataclasses import asdict

from app.analyzer.collector import collect_repository_snapshot
from app.analyzer.scoring import score_repository
from app.github.client import GithubClient
from app.github.url_parser import parse_github_repo_url


@bp.post("/api/analyze")
def analyze_repository():
    payload = request.get_json(silent=True) or {}
    ref = parse_github_repo_url(payload.get("url", ""))
    settings = current_app.config["APP_SETTINGS"]
    client = GithubClient(base_url=settings.github_api_base_url)
    snapshot = collect_repository_snapshot(client, ref)
    score = score_repository(snapshot)
    return jsonify(
        {
            "repository": asdict(snapshot.repo),
            "languages": snapshot.languages,
            "community": asdict(snapshot.community),
            "activity": asdict(snapshot.activity),
            "score": asdict(score),
        }
    )
```

- [ ] **Step 4: Add route success test with monkeypatch**

Append to `tests/test_routes_analyze.py`:

```python
def test_analyze_returns_score(monkeypatch):
    from app.models import ActivityInfo, CommunityInfo, RepoInfo, RepositorySnapshot

    def fake_collect(client, ref):
        return RepositorySnapshot(
            repo=RepoInfo(
                full_name="owner/repo",
                description="Example",
                stars=10,
                forks=1,
                watchers=1,
                open_issues=0,
                default_branch="main",
                license_spdx="MIT",
                archived=False,
                disabled=False,
                fork=False,
                pushed_at="2026-05-20T00:00:00Z",
                updated_at="2026-05-21T00:00:00Z",
                created_at="2025-01-01T00:00:00Z",
                size_kb=10,
            ),
            languages={"Python": 100.0},
            community=CommunityInfo(health_percentage=80, files={"readme": True, "license": True}),
            activity=ActivityInfo(20, 2, 1, "2026-05-01T00:00:00Z", 0),
        )

    monkeypatch.setattr("app.routes.collect_repository_snapshot", fake_collect)
    app = create_app(Settings.from_env())
    client = app.test_client()

    response = client.post("/api/analyze", json={"url": "https://github.com/owner/repo"})

    assert response.status_code == 200
    assert response.json["repository"]["full_name"] == "owner/repo"
    assert response.json["score"]["score"] >= 0
```

- [ ] **Step 5: Run route tests and commit**

Run: `pytest tests/test_routes_analyze.py -v`

Expected: all route tests pass.

Commit:

```powershell
git add app/routes.py tests/test_routes_analyze.py
git commit -m "feat: add repository analysis api"
```

### Task 8: Frontend Page and Charts

**Files:**
- Create: `templates/index.html`
- Create: `static/css/styles.css`
- Create: `static/js/app.js`
- Modify: `app/routes.py`

- [ ] **Step 1: Add page route smoke test**

Create `tests/test_frontend_route.py`:

```python
from app import create_app
from app.config import Settings


def test_index_page_renders():
    app = create_app(Settings.from_env())
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert "Github 仓库体检" in response.get_data(as_text=True)
```

- [ ] **Step 2: Run smoke test and verify failure**

Run: `pytest tests/test_frontend_route.py -v`

Expected: 404 because `/` is not implemented.

- [ ] **Step 3: Add frontend files**

Create `templates/index.html` with a single usable app screen containing:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Github 仓库体检</title>
  <link rel="stylesheet" href="/static/css/styles.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
  <main class="shell">
    <section class="toolbar">
      <div>
        <h1>Github 仓库体检</h1>
        <p>输入公开仓库或已授权私有仓库 URL，查看系统评分和可视化指标。</p>
      </div>
      <a class="ghost-button" href="/github-app/install">安装 GitHub App</a>
    </section>
    <form id="repo-form" class="search-row">
      <input id="repo-url" name="url" type="url" placeholder="https://github.com/owner/repo" required>
      <button type="submit">开始体检</button>
    </form>
    <div id="message" class="message"></div>
    <section id="summary" class="summary hidden"></section>
    <section class="grid">
      <canvas id="language-chart"></canvas>
      <canvas id="score-chart"></canvas>
    </section>
    <section id="risks" class="risks hidden"></section>
    <section id="agent-panel" class="agent hidden">
      <button id="agent-button" type="button">启动 AI 深度分析</button>
      <pre id="agent-output"></pre>
    </section>
  </main>
  <script src="/static/js/app.js"></script>
</body>
</html>
```

Create `static/js/app.js` with fetch/render logic:

```javascript
const form = document.querySelector("#repo-form");
const message = document.querySelector("#message");
const summary = document.querySelector("#summary");
const risks = document.querySelector("#risks");
const agentPanel = document.querySelector("#agent-panel");

let languageChart;
let scoreChart;

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "分析中...";
  summary.classList.add("hidden");
  risks.classList.add("hidden");
  const url = document.querySelector("#repo-url").value;
  const response = await fetch("/api/analyze", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({url})
  });
  const data = await response.json();
  if (!response.ok) {
    message.textContent = data.message || "分析失败";
    return;
  }
  message.textContent = "";
  renderSummary(data);
  renderCharts(data);
  renderRisks(data.score.risks, data.score.recommendations);
  agentPanel.classList.remove("hidden");
});

function renderSummary(data) {
  summary.classList.remove("hidden");
  summary.innerHTML = `
    <div class="score">${data.score.score}<span>/100</span></div>
    <div>
      <h2>${data.repository.full_name}</h2>
      <p>${data.repository.description || ""}</p>
      <div class="metrics">
        <span>Stars ${data.repository.stars}</span>
        <span>Forks ${data.repository.forks}</span>
        <span>Issues ${data.repository.open_issues}</span>
        <span>Status ${data.score.status}</span>
      </div>
    </div>`;
}

function renderCharts(data) {
  if (languageChart) languageChart.destroy();
  if (scoreChart) scoreChart.destroy();
  languageChart = new Chart(document.querySelector("#language-chart"), {
    type: "doughnut",
    data: {labels: Object.keys(data.languages), datasets: [{data: Object.values(data.languages)}]}
  });
  scoreChart = new Chart(document.querySelector("#score-chart"), {
    type: "bar",
    data: {labels: Object.keys(data.score.dimensions), datasets: [{data: Object.values(data.score.dimensions)}]},
    options: {plugins: {legend: {display: false}}}
  });
}

function renderRisks(riskItems, recommendations) {
  risks.classList.remove("hidden");
  risks.innerHTML = `<h2>风险与建议</h2>${[...riskItems.map(r => r.message), ...recommendations].map(item => `<p>${item}</p>`).join("")}`;
}
```

Create `static/css/styles.css` with responsive app styling:

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: Arial, "Microsoft YaHei", sans-serif; background: #f7f8fb; color: #20242a; }
.shell { max-width: 1120px; margin: 0 auto; padding: 32px 20px; }
.toolbar { display: flex; justify-content: space-between; gap: 16px; align-items: center; }
h1 { margin: 0 0 8px; font-size: 32px; }
.search-row { display: grid; grid-template-columns: 1fr auto; gap: 12px; margin: 24px 0; }
input, button, .ghost-button { border-radius: 6px; border: 1px solid #c7ccd6; padding: 12px 14px; font-size: 15px; }
button, .ghost-button { background: #1f6feb; color: white; cursor: pointer; text-decoration: none; }
.ghost-button { background: white; color: #1f6feb; }
.message { min-height: 24px; color: #9a3412; }
.summary, .risks, .agent { background: white; border: 1px solid #e1e4ea; border-radius: 8px; padding: 20px; margin: 16px 0; }
.summary { display: flex; gap: 20px; align-items: center; }
.score { font-size: 48px; font-weight: 700; color: #146c43; }
.score span { font-size: 18px; color: #5f6b7a; }
.metrics { display: flex; flex-wrap: wrap; gap: 8px; }
.metrics span { background: #edf2f7; border-radius: 999px; padding: 6px 10px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
canvas { background: white; border: 1px solid #e1e4ea; border-radius: 8px; padding: 16px; max-height: 360px; }
.hidden { display: none; }
@media (max-width: 720px) {
  .toolbar, .summary { align-items: stretch; flex-direction: column; }
  .search-row, .grid { grid-template-columns: 1fr; }
}
```

- [ ] **Step 4: Add index route**

Modify `app/routes.py`:

```python
from flask import render_template


@bp.get("/")
def index():
    return render_template("index.html")
```

- [ ] **Step 5: Run frontend smoke test and commit**

Run: `pytest tests/test_frontend_route.py -v`

Expected: all frontend route tests pass.

Commit:

```powershell
git add templates static app/routes.py tests/test_frontend_route.py
git commit -m "feat: add repository health frontend"
```

### Task 9: Basic Agent Github Tools

**Files:**
- Create: `app/agent/__init__.py`
- Create: `app/agent/tools.py`
- Create: `tests/test_agent_tools.py`

- [ ] **Step 1: Write agent tool tests**

Create `tests/test_agent_tools.py`:

```python
from app.agent.tools import GithubAgentTools
from app.github.url_parser import RepoRef


class FakeClient:
    def get_json(self, path, params=None):
        if path.endswith("/languages"):
            return {"Python": 100}
        if path.endswith("/releases"):
            return [{"tag_name": "v1.0.0"}]
        return {"full_name": "owner/repo", "stargazers_count": 10}


def test_basic_tool_summary():
    tools = GithubAgentTools(FakeClient(), RepoRef("owner", "repo"), private_mode=False, permissions={})

    result = tools.get_repo_summary()

    assert result["full_name"] == "owner/repo"


def test_unavailable_private_tool_without_permission():
    tools = GithubAgentTools(FakeClient(), RepoRef("owner", "repo"), private_mode=True, permissions={})

    result = tools.get_actions_runs_summary()

    assert result["available"] is False
    assert result["missing_permission"] == "actions:read"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_agent_tools.py -v`

Expected: import failure for `app.agent.tools`.

- [ ] **Step 3: Implement controlled tools**

Create `app/agent/__init__.py`:

```python
"""AI agent package."""
```

Create `app/agent/tools.py`:

```python
from __future__ import annotations

from app.github.client import GithubClient
from app.github.url_parser import RepoRef


class GithubAgentTools:
    def __init__(self, client: GithubClient, ref: RepoRef, private_mode: bool, permissions: dict[str, str]):
        self.client = client
        self.ref = ref
        self.private_mode = private_mode
        self.permissions = permissions
        self.base = f"/repos/{ref.owner}/{ref.repo}"

    def get_repo_summary(self) -> dict:
        data = self.client.get_json(self.base)
        return {
            "full_name": data.get("full_name"),
            "stars": data.get("stargazers_count", 0),
            "forks": data.get("forks_count", 0),
            "open_issues": data.get("open_issues_count", 0),
            "archived": data.get("archived", False),
            "fork": data.get("fork", False),
            "source": f"https://github.com/{self.ref.full_name}",
        }

    def get_language_breakdown(self) -> dict:
        return self.client.get_json(f"{self.base}/languages")

    def get_releases(self) -> dict:
        return {"items": self.client.get_json(f"{self.base}/releases", params={"per_page": 10})}

    def get_actions_runs_summary(self) -> dict:
        if not self._has("actions", "read"):
            return self._unavailable("actions:read")
        runs = self.client.get_json(f"{self.base}/actions/runs", params={"per_page": 20})
        return {"available": True, "runs": runs.get("workflow_runs", [])}

    def _has(self, permission: str, level: str) -> bool:
        granted = self.permissions.get(permission)
        return granted == level or granted == "write"

    @staticmethod
    def _unavailable(permission: str) -> dict:
        return {"available": False, "missing_permission": permission}
```

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests/test_agent_tools.py -v`

Expected: all agent tool tests pass.

Commit:

```powershell
git add app/agent tests/test_agent_tools.py
git commit -m "feat: add controlled github agent tools"
```

### Task 10: Agent LLM and Tavily Orchestration

**Files:**
- Create: `app/agent/llm.py`
- Create: `app/agent/tavily.py`
- Create: `app/agent/service.py`
- Create: `tests/test_agent_service.py`
- Modify: `app/routes.py`

- [ ] **Step 1: Write agent service tests**

Create `tests/test_agent_service.py`:

```python
from app.agent.service import build_agent_prompt, should_enable_tavily


def test_tavily_enabled_only_for_public_repo_with_key():
    assert should_enable_tavily(private_mode=False, tavily_api_key="key") is True
    assert should_enable_tavily(private_mode=True, tavily_api_key="key") is False
    assert should_enable_tavily(private_mode=False, tavily_api_key=None) is False


def test_prompt_includes_system_score():
    prompt = build_agent_prompt(
        repo_url="https://github.com/owner/repo",
        system_score={"score": 80, "status": "良好"},
        private_mode=False,
    )

    assert "https://github.com/owner/repo" in prompt
    assert "80" in prompt
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_agent_service.py -v`

Expected: import failure for `app.agent.service`.

- [ ] **Step 3: Implement model, Tavily, and service skeleton**

Create `app/agent/llm.py`:

```python
from __future__ import annotations

from openai import OpenAI


class LlmClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def complete_json(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是 Github 仓库健康分析 agent，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or "{}"
```

Create `app/agent/tavily.py`:

```python
from __future__ import annotations

import requests


class TavilyClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str) -> list[dict]:
        response = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": self.api_key, "query": query, "search_depth": "basic", "max_results": 5},
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("results", [])
```

Create `app/agent/service.py`:

```python
from __future__ import annotations

import json


def should_enable_tavily(private_mode: bool, tavily_api_key: str | None) -> bool:
    return bool(tavily_api_key) and not private_mode


def build_agent_prompt(repo_url: str, system_score: dict, private_mode: bool) -> str:
    mode = "私有仓库，仅使用 Github API 包装工具" if private_mode else "公开仓库，可使用 Github API 包装工具和 Tavily"
    return (
        f"仓库：{repo_url}\n"
        f"模式：{mode}\n"
        f"系统评分：{json.dumps(system_score, ensure_ascii=False)}\n"
        "请返回 JSON，包含 ai_score、confidence、summary、findings、recommendations。"
    )
```

- [ ] **Step 4: Add `/api/agent/analyze` route with configuration gate**

Modify `app/routes.py`:

```python
from app.agent.service import build_agent_prompt


@bp.post("/api/agent/analyze")
def agent_analyze():
    settings = current_app.config["APP_SETTINGS"]
    if not settings.agent_configured:
        raise ValidationError("模型参数未配置，无法启动 AI 深度分析。")
    payload = request.get_json(silent=True) or {}
    repo_url = payload.get("url", "")
    system_score = payload.get("system_score", {})
    private_mode = bool(payload.get("private_mode", False))
    prompt = build_agent_prompt(repo_url, system_score, private_mode)
    return jsonify({"status": "queued", "prompt_preview": prompt[:300]})
```

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_agent_service.py tests/test_routes_analyze.py -v`

Expected: all tests pass.

Commit:

```powershell
git add app/agent app/routes.py tests/test_agent_service.py
git commit -m "feat: add agent analysis orchestration"
```

### Task 11: Private Repository Enhanced Tools

**Files:**
- Modify: `app/agent/tools.py`
- Create: `tests/test_private_agent_tools.py`

- [ ] **Step 1: Write enhanced tool permission tests**

Create `tests/test_private_agent_tools.py`:

```python
from app.agent.tools import GithubAgentTools
from app.github.url_parser import RepoRef


class FakeClient:
    def get_json(self, path, params=None):
        if path.endswith("/traffic/views"):
            return {"count": 10, "uniques": 5, "views": []}
        if path.endswith("/dependency-graph/sbom"):
            return {"sbom": {"packages": [{"name": "flask"}]}}
        if path.endswith("/dependabot/alerts"):
            return [{"state": "open", "security_vulnerability": {"severity": "high"}}]
        return {}


def test_traffic_tool_requires_administration_read():
    tools = GithubAgentTools(FakeClient(), RepoRef("owner", "repo"), True, {"administration": "read"})

    result = tools.get_traffic_summary()

    assert result["available"] is True
    assert result["views"]["count"] == 10


def test_dependabot_tool_summarizes_alerts():
    tools = GithubAgentTools(FakeClient(), RepoRef("owner", "repo"), True, {"dependabot_alerts": "read"})

    result = tools.get_dependabot_alerts_summary()

    assert result["available"] is True
    assert result["open_alerts"] == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_private_agent_tools.py -v`

Expected: missing enhanced tool methods.

- [ ] **Step 3: Implement enhanced tools**

Append to `GithubAgentTools` in `app/agent/tools.py`:

```python
    def get_traffic_summary(self) -> dict:
        if not self._has("administration", "read"):
            return self._unavailable("administration:read")
        return {
            "available": True,
            "views": self.client.get_json(f"{self.base}/traffic/views"),
            "clones": self.client.get_json(f"{self.base}/traffic/clones"),
        }

    def get_sbom_summary(self) -> dict:
        if not self._has("contents", "read"):
            return self._unavailable("contents:read")
        data = self.client.get_json(f"{self.base}/dependency-graph/sbom")
        packages = data.get("sbom", {}).get("packages", [])
        return {"available": True, "package_count": len(packages)}

    def get_dependabot_alerts_summary(self) -> dict:
        if not self._has("dependabot_alerts", "read"):
            return self._unavailable("dependabot_alerts:read")
        alerts = self.client.get_json(f"{self.base}/dependabot/alerts", params={"per_page": 100})
        open_alerts = [alert for alert in alerts if alert.get("state") == "open"]
        return {"available": True, "open_alerts": len(open_alerts)}

    def get_code_scanning_alerts_summary(self) -> dict:
        if not self._has("code_scanning_alerts", "read"):
            return self._unavailable("code_scanning_alerts:read")
        alerts = self.client.get_json(f"{self.base}/code-scanning/alerts", params={"per_page": 100})
        return {"available": True, "open_alerts": len([item for item in alerts if item.get("state") == "open"])}

    def get_secret_scanning_alerts_summary(self) -> dict:
        if not self._has("secret_scanning_alerts", "read"):
            return self._unavailable("secret_scanning_alerts:read")
        alerts = self.client.get_json(f"{self.base}/secret-scanning/alerts", params={"per_page": 100})
        return {"available": True, "open_alerts": len([item for item in alerts if item.get("state") == "open"])}
```

- [ ] **Step 4: Run enhanced tool tests and commit**

Run: `pytest tests/test_private_agent_tools.py tests/test_agent_tools.py -v`

Expected: all agent tool tests pass.

Commit:

```powershell
git add app/agent/tools.py tests/test_private_agent_tools.py
git commit -m "feat: add private repository enhanced agent tools"
```

### Task 12: Documentation, Manual Verification, and Local Run

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Create: `run.py`
- Create: `tests/test_app_factory.py`

- [ ] **Step 1: Add app factory test**

Create `tests/test_app_factory.py`:

```python
from app import create_app
from app.config import Settings


def test_app_factory_registers_health_route():
    app = create_app(Settings.from_env())
    client = app.test_client()

    response = client.get("/api/health")

    assert response.status_code == 200
```

- [ ] **Step 2: Add run entrypoint**

Create `run.py`:

```python
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
```

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`

Expected: all tests pass.

- [ ] **Step 4: Start the local server**

Run: `python run.py`

Expected: Flask reports it is serving at `http://127.0.0.1:5000`.

- [ ] **Step 5: Open and verify the page**

Open `http://127.0.0.1:5000` in the browser. Analyze `https://github.com/pallets/flask`.

Expected:

- Page loads without console errors.
- System score is visible.
- Stars, Forks, Open Issues, default branch, and language chart are visible.
- Risk/recommendation section renders.

- [ ] **Step 6: Commit final implementation**

Commit:

```powershell
git add .
git commit -m "docs: finalize setup and verification instructions"
```

## Self-Review

- Spec coverage: public repository analysis, GitHub App installation path, deterministic system scoring, optional agent analysis, Tavily public-only behavior, private enhanced Github API tools, environment configuration, and error handling are covered by tasks above.
- Placeholder scan: no unresolved placeholders or vague implementation steps remain in this plan.
- Type consistency: planned modules consistently use `RepoRef`, `GithubClient`, `RepositorySnapshot`, `ScoreResult`, `GithubAgentTools`, and `Settings`.

## Execution Options

Plan complete and saved to `docs/superpowers/plans/2026-05-26-github-repo-health-implementation.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
