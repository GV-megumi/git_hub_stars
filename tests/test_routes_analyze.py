from __future__ import annotations

import json
from pathlib import Path

from app import create_app
from app.analyzer.scoring import ScoreResult
from app.config import Settings
from app.models import ActivityInfo, CommunityInfo, RepoInfo, RepositorySnapshot


def test_analyze_rejects_bad_url():
    app = create_app(make_settings())
    client = app.test_client()

    response = client.post("/api/analyze", json={"url": "bad"})

    assert response.status_code == 400
    assert response.json["error"] == "validation_error"


def test_health_endpoint_still_works():
    app = create_app(make_settings())
    client = app.test_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}


def test_analyze_public_repository_returns_score_without_github_app_config(monkeypatch):
    from app import routes

    monkeypatch.setenv("GITHUB_TOKEN", "env-token-must-not-be-used")
    created_clients = []
    collected_refs = []
    scored_snapshots = []

    class FakeGithubClient:
        def __init__(self, base_url: str, token: str | None = None):
            self.base_url = base_url
            self.token = token
            created_clients.append(self)

    snapshot = RepositorySnapshot(
        repo=RepoInfo(
            full_name="owner/repo",
            description="Example repository",
            stars=10,
            forks=2,
            watchers=3,
            open_issues=1,
            default_branch="main",
            license_spdx="MIT",
            archived=False,
            disabled=False,
            fork=False,
            pushed_at="2026-05-20T00:00:00Z",
            updated_at="2026-05-21T00:00:00Z",
            created_at="2025-01-01T00:00:00Z",
            size_kb=123,
        ),
        languages={"Python": 80.0, "HTML": 20.0},
        community=CommunityInfo(health_percentage=80, files={"readme": True, "license": True}),
        activity=ActivityInfo(
            recent_commits_count=6,
            commits_30d_count=3,
            commits_90d_count=6,
            contributors_count=2,
            releases_count=1,
            latest_release_at="2026-05-01T00:00:00Z",
            open_pulls_count=0,
        ),
        partial_errors=[],
    )
    score = ScoreResult(
        score=81,
        status="良好",
        dimensions={"活跃维护": 80},
        risks=[],
        recommendations=["Keep release notes current."],
    )

    def fake_collect(client, ref):
        assert client is created_clients[0]
        collected_refs.append(ref)
        return snapshot

    def fake_score(received_snapshot):
        scored_snapshots.append(received_snapshot)
        return score

    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient, raising=False)
    monkeypatch.setattr(routes, "collect_repository_snapshot", fake_collect, raising=False)
    monkeypatch.setattr(routes, "score_repository", fake_score, raising=False)
    app = create_app(make_settings(github_api_base_url="https://api.example.test"))
    client = app.test_client()

    response = client.post("/api/analyze", json={"url": "https://github.com/owner/repo"})

    assert response.status_code == 200
    payload = response.json
    assert app.config["APP_SETTINGS"].github_app_configured is False
    assert created_clients[0].base_url == "https://api.example.test"
    assert created_clients[0].token is None
    assert collected_refs[0].full_name == "owner/repo"
    assert scored_snapshots == [snapshot]
    assert payload["repository"]["full_name"] == "owner/repo"
    assert payload["score"]["score"] == 81
    assert payload["languages"] == {"Python": 80.0, "HTML": 20.0}
    assert payload["community"]["health_percentage"] == 80
    assert payload["activity"]["recent_commits_count"] == 6
    assert payload["partial_errors"] == []
    assert payload["private_mode"] is False


def test_analyze_rejects_non_boolean_private_mode(monkeypatch):
    from app import routes

    def fail_collect(_client, _ref):
        raise AssertionError("analysis should not start with invalid private_mode")

    monkeypatch.setattr(routes, "collect_repository_snapshot", fail_collect, raising=False)
    app = create_app(make_settings())
    client = app.test_client()

    response = client.post(
        "/api/analyze",
        json={"url": "https://github.com/owner/repo", "private_mode": "true"},
    )

    assert response.status_code == 400
    assert response.json["error"] == "validation_error"


def test_analyze_private_mode_requires_installed_github_app():
    app = create_app(make_settings())
    client = app.test_client()

    response = client.post(
        "/api/analyze",
        json={"url": "https://github.com/owner/private-repo", "private_mode": True},
    )

    assert response.status_code == 403
    assert response.json["error"] == "permission_required"


def test_analyze_private_mode_requires_configured_github_app(monkeypatch):
    from app import routes

    created_clients = []

    class FakeGithubClient:
        def __init__(self, base_url: str, token: str | None = None):
            created_clients.append({"base_url": base_url, "token": token})

    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient, raising=False)
    app = create_app(make_settings())
    client = app.test_client()
    with client.session_transaction() as session:
        session["github_installation_id"] = "789"

    response = client.post(
        "/api/analyze",
        json={"url": "https://github.com/owner/private-repo", "private_mode": True},
    )

    assert response.status_code == 400
    assert response.json["error"] == "validation_error"
    assert created_clients == []


def test_analyze_private_mode_uses_installation_token_without_leaking_it(monkeypatch):
    from app import routes

    auth_instances = []
    created_clients = []
    collected_refs = []
    snapshot = make_snapshot(full_name="owner/private-repo")
    score = make_score()

    class FakeGithubAppAuth:
        def __init__(self, app_slug, app_id, private_key_path, api_base_url="https://api.github.com"):
            self.app_slug = app_slug
            self.app_id = app_id
            self.private_key_path = private_key_path
            self.api_base_url = api_base_url
            self.create_installation_token_calls = []
            auth_instances.append(self)

        def create_installation_token(self, installation_id, repositories=None, permissions=None):
            self.create_installation_token_calls.append(
                {
                    "installation_id": installation_id,
                    "repositories": repositories,
                    "permissions": permissions,
                }
            )
            return {"token": "installation-token"}

    class FakeGithubClient:
        def __init__(self, base_url: str, token: str | None = None):
            self.base_url = base_url
            self.token = token
            created_clients.append(self)

    def fake_collect(client, ref):
        assert client is created_clients[0]
        assert client.token == "installation-token"
        collected_refs.append(ref)
        return snapshot

    monkeypatch.setattr(routes, "GithubAppAuth", FakeGithubAppAuth, raising=False)
    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient, raising=False)
    monkeypatch.setattr(routes, "collect_repository_snapshot", fake_collect, raising=False)
    monkeypatch.setattr(routes, "score_repository", lambda _snapshot: score, raising=False)
    app = create_app(make_settings(configured=True, github_api_base_url="https://api.example.test"))
    client = app.test_client()
    with client.session_transaction() as session:
        session["github_installation_id"] = "789"

    response = client.post(
        "/api/analyze",
        json={"url": "https://github.com/owner/private-repo", "private_mode": True},
    )

    assert response.status_code == 200
    payload = response.json
    assert len(auth_instances) == 1
    assert auth_instances[0].app_slug == "repo-health"
    assert auth_instances[0].app_id == "123"
    assert auth_instances[0].private_key_path == Path("secrets/github-app-private-key.pem")
    assert auth_instances[0].api_base_url == "https://api.example.test"
    assert auth_instances[0].create_installation_token_calls == [
        {
            "installation_id": "789",
            "repositories": ["private-repo"],
            "permissions": {"contents": "read", "metadata": "read"},
        }
    ]
    assert created_clients[0].base_url == "https://api.example.test"
    assert created_clients[0].token == "installation-token"
    assert collected_refs[0].full_name == "owner/private-repo"
    assert collected_refs[0].repo == "private-repo"
    assert payload["private_mode"] is True
    assert "installation-token" not in json.dumps(payload)
    with client.session_transaction() as session:
        assert "github_installation_token" not in session


def test_analyze_private_mode_rejects_token_response_without_token(monkeypatch):
    from app import routes

    created_clients = []

    class FakeGithubAppAuth:
        def __init__(self, app_slug, app_id, private_key_path, api_base_url="https://api.github.com"):
            pass

        def create_installation_token(self, installation_id, repositories=None, permissions=None):
            return {"expires_at": "2026-05-26T00:00:00Z"}

    class FakeGithubClient:
        def __init__(self, base_url: str, token: str | None = None):
            created_clients.append({"base_url": base_url, "token": token})

    monkeypatch.setattr(routes, "GithubAppAuth", FakeGithubAppAuth, raising=False)
    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient, raising=False)
    app = create_app(make_settings(configured=True))
    client = app.test_client()
    with client.session_transaction() as session:
        session["github_installation_id"] = "789"

    response = client.post(
        "/api/analyze",
        json={"url": "https://github.com/owner/private-repo", "private_mode": True},
    )

    assert response.status_code == 400
    assert response.json["error"] == "validation_error"
    assert created_clients == []


def make_snapshot(full_name: str = "owner/repo") -> RepositorySnapshot:
    return RepositorySnapshot(
        repo=RepoInfo(
            full_name=full_name,
            description="Example repository",
            stars=10,
            forks=2,
            watchers=3,
            open_issues=1,
            default_branch="main",
            license_spdx="MIT",
            archived=False,
            disabled=False,
            fork=False,
            pushed_at="2026-05-20T00:00:00Z",
            updated_at="2026-05-21T00:00:00Z",
            created_at="2025-01-01T00:00:00Z",
            size_kb=123,
        ),
        languages={"Python": 80.0, "HTML": 20.0},
        community=CommunityInfo(health_percentage=80, files={"readme": True, "license": True}),
        activity=ActivityInfo(
            recent_commits_count=6,
            commits_30d_count=3,
            commits_90d_count=6,
            contributors_count=2,
            releases_count=1,
            latest_release_at="2026-05-01T00:00:00Z",
            open_pulls_count=0,
        ),
        partial_errors=[],
    )


def make_score() -> ScoreResult:
    return ScoreResult(
        score=81,
        status="ok",
        dimensions={"activity": 80},
        risks=[],
        recommendations=["Keep release notes current."],
    )


def make_settings(
    configured: bool = False,
    github_api_base_url: str = "https://api.github.com",
) -> Settings:
    return Settings(
        flask_env="testing",
        flask_secret_key="test-secret-key",
        github_app_id="123" if configured else None,
        github_app_slug="repo-health" if configured else None,
        github_app_private_key_path=Path("secrets/github-app-private-key.pem") if configured else None,
        github_app_setup_url="http://127.0.0.1:5000/github-app/setup" if configured else None,
        tavily_api_key=None,
        model_base_url=None,
        model_api_key=None,
        model_name=None,
        github_api_base_url=github_api_base_url,
    )
