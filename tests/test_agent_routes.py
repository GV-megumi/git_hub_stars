from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import create_app
from app.agent.service import should_enable_tavily
from app.config import Settings


def test_agent_analyze_requires_model_configuration():
    app = create_app(make_settings(model_configured=False))
    client = app.test_client()

    response = client.post(
        "/api/agent/analyze",
        json={"url": "https://github.com/owner/repo", "system_score": {"score": 80}},
    )

    assert response.status_code == 400
    assert response.json["error"] == "validation_error"
    assert "模型" in response.json["message"]


def test_public_agent_route_uses_anonymous_github_client_and_service(monkeypatch):
    from app import routes

    created_clients = []
    service_calls = []

    class FakeGithubClient:
        def __init__(self, base_url, token=None):
            self.base_url = base_url
            self.token = token
            created_clients.append(self)

    def fake_run_agent_analysis(**kwargs):
        service_calls.append(kwargs)
        return {
            "ai_score": 91,
            "confidence": "high",
            "summary": "公开仓库分析完成。",
            "findings": [],
            "recommendations": [],
            "references": [],
            "used_tools": ["github.get_repo_summary"],
            "tavily_enabled": True,
        }

    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient)
    monkeypatch.setattr(routes, "run_agent_analysis", fake_run_agent_analysis)
    app = create_app(
        make_settings(
            model_configured=True,
            tavily_api_key="tavily-key",
            github_api_base_url="https://api.example.test",
        )
    )
    client = app.test_client()
    analysis_id = seed_completed_analysis(
        app,
        client,
        repo_url="https://github.com/owner/repo",
        private_mode=False,
        system_score={"score": 80, "status": "良好"},
        detected_info={"languages": {"Python": 90.0}},
    )

    response = client.post(
        "/api/agent/analyze",
        json={
            "analysis_id": analysis_id,
            "url": "https://github.com/evil/repo",
            "system_score": {"score": 1},
            "detected_info": {"languages": {"Shell": 100.0}},
            "private_mode": True,
        },
    )

    assert response.status_code == 200
    assert response.json["ai_score"] == 91
    assert len(created_clients) == 1
    assert created_clients[0].base_url == "https://api.example.test"
    assert created_clients[0].token is None
    assert len(service_calls) == 1
    assert service_calls[0]["repo_url"] == "https://github.com/owner/repo"
    assert service_calls[0]["ref"].full_name == "owner/repo"
    assert service_calls[0]["system_score"] == {"score": 80, "status": "良好"}
    assert service_calls[0]["detected_info"] == {"languages": {"Python": 90.0}}
    assert service_calls[0]["private_mode"] is False
    assert service_calls[0]["github_client"] is created_clients[0]
    assert service_calls[0]["settings"] is app.config["APP_SETTINGS"]
    assert service_calls[0]["settings"].tavily_api_key == "tavily-key"
    assert service_calls[0]["permissions"] == {}


def test_agent_route_requires_completed_system_analysis_before_service(monkeypatch):
    from app import routes

    created_clients = []
    service_calls = []

    class FakeGithubClient:
        def __init__(self, base_url, token=None):
            created_clients.append({"base_url": base_url, "token": token})

    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient)
    monkeypatch.setattr(routes, "run_agent_analysis", lambda **kwargs: service_calls.append(kwargs))
    app = create_app(make_settings(model_configured=True, tavily_api_key="tavily-key"))
    client = app.test_client()

    response = client.post(
        "/api/agent/analyze",
        json={
            "url": "https://github.com/owner/repo",
            "private_mode": False,
            "system_score": {"score": 80},
        },
    )

    assert response.status_code == 403
    assert response.json["error"] == "permission_required"
    assert created_clients == []
    assert service_calls == []


def test_agent_route_accepts_session_owned_analysis_when_last_id_cookie_is_stale(monkeypatch):
    from app import routes

    service_calls = []

    class FakeGithubClient:
        def __init__(self, base_url, token=None):
            pass

    def fake_run_agent_analysis(**kwargs):
        service_calls.append(kwargs)
        return {"ai_score": 88, "tavily_enabled": True}

    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient)
    monkeypatch.setattr(routes, "run_agent_analysis", fake_run_agent_analysis)
    app = create_app(make_settings(model_configured=True, tavily_api_key="tavily-key"))
    client = app.test_client()
    accepted_id = seed_completed_analysis(
        app,
        client,
        repo_url="https://github.com/owner/current",
        private_mode=False,
        system_score={"score": 82},
        detected_info={"repository": {"full_name": "owner/current"}},
        analysis_id="accepted-analysis",
    )
    with client.session_transaction() as session:
        session["last_analysis_id"] = "stale-analysis"

    response = client.post("/api/agent/analyze", json={"analysis_id": accepted_id})

    assert response.status_code == 200
    assert service_calls[0]["repo_url"] == "https://github.com/owner/current"
    assert service_calls[0]["system_score"] == {"score": 82}


def test_agent_route_rejects_analysis_id_from_other_session_owner(monkeypatch):
    from app import routes

    service_calls = []

    class FakeGithubClient:
        def __init__(self, base_url, token=None):
            pass

    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient)
    monkeypatch.setattr(routes, "run_agent_analysis", lambda **kwargs: service_calls.append(kwargs))
    app = create_app(make_settings(model_configured=True, tavily_api_key="tavily-key"))
    client = app.test_client()
    app.extensions.setdefault("repo_health_analysis_cache", {})["foreign-analysis"] = {
        "owner_id": "other-owner",
        "url": "https://github.com/owner/repo",
        "private_mode": False,
        "system_score": {"score": 80},
        "detected_info": {},
    }
    with client.session_transaction() as session:
        session["analysis_owner_id"] = "current-owner"
        session["last_analysis_id"] = "foreign-analysis"

    response = client.post("/api/agent/analyze", json={"analysis_id": "foreign-analysis"})

    assert response.status_code == 403
    assert response.json["error"] == "permission_required"
    assert service_calls == []


@pytest.mark.parametrize(
    "extra_payload",
    [
        {},
        {"confirm_private_data_to_model": False},
        {"confirm_private_data_to_model": "true"},
    ],
)
def test_private_agent_route_requires_explicit_model_data_confirmation_before_token_or_service(
    monkeypatch,
    extra_payload,
):
    from app import routes

    token_calls = []
    created_clients = []
    service_calls = []

    def fake_private_installation_token(repo_name):
        token_calls.append(repo_name)
        return "installation-token"

    class FakeGithubClient:
        def __init__(self, base_url, token=None):
            created_clients.append({"base_url": base_url, "token": token})

    def fake_run_agent_analysis(**kwargs):
        service_calls.append(kwargs)
        return {"ai_score": 1}

    monkeypatch.setattr(routes, "_private_installation_token", fake_private_installation_token)
    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient)
    monkeypatch.setattr(routes, "run_agent_analysis", fake_run_agent_analysis)
    app = create_app(make_settings(model_configured=True, github_configured=True, tavily_api_key="tavily-key"))
    client = app.test_client()
    analysis_id = seed_completed_analysis(
        app,
        client,
        repo_url="https://github.com/owner/private-repo",
        private_mode=True,
        system_score={"score": 60},
        detected_info={"private": True},
    )

    payload = {
        "analysis_id": analysis_id,
        "url": "https://github.com/owner/private-repo",
        "private_mode": False,
    }
    payload.update(extra_payload)
    response = client.post("/api/agent/analyze", json=payload)

    assert response.status_code in {400, 403}
    assert response.json["error"] in {"validation_error", "permission_required"}
    assert token_calls == []
    assert created_clients == []
    assert service_calls == []


def test_private_agent_route_uses_installation_token_and_keeps_tavily_disabled(monkeypatch):
    from app import routes

    auth_instances = []
    created_clients = []
    service_calls = []

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
        def __init__(self, base_url, token=None):
            self.base_url = base_url
            self.token = token
            created_clients.append(self)

    def fake_run_agent_analysis(**kwargs):
        service_calls.append(kwargs)
        assert kwargs["private_mode"] is True
        assert kwargs["github_client"].token == "installation-token"
        assert should_enable_tavily(
            kwargs["private_mode"],
            kwargs["settings"].tavily_api_key,
        ) is False
        return {
            "ai_score": 67,
            "confidence": "medium",
            "summary": "私有仓库分析完成。",
            "findings": [],
            "recommendations": [],
            "references": [],
            "used_tools": ["github.get_repo_summary"],
            "tavily_enabled": False,
        }

    monkeypatch.setattr(routes, "GithubAppAuth", FakeGithubAppAuth)
    monkeypatch.setattr(routes, "GithubClient", FakeGithubClient)
    monkeypatch.setattr(routes, "run_agent_analysis", fake_run_agent_analysis)
    app = create_app(make_settings(model_configured=True, github_configured=True, tavily_api_key="tavily-key"))
    client = app.test_client()
    analysis_id = seed_completed_analysis(
        app,
        client,
        repo_url="https://github.com/owner/private-repo",
        private_mode=True,
        system_score={"score": 60},
        detected_info={"private": True},
    )
    with client.session_transaction() as session:
        session["github_installation_id"] = "789"
        session["github_installation_permissions"] = {
            "actions": "read",
            "checks": "read",
            "metadata": "read",
            "issues": "read",
            "deployments": "read",
            "vulnerability_alerts": "read",
            "administration": "write",
            "repository_advisories": "read",
            "security_events": "read",
            "secret_scanning_alerts": "none",
        }

    response = client.post(
        "/api/agent/analyze",
        json={
            "analysis_id": analysis_id,
            "url": "https://github.com/evil/repo",
            "system_score": {"score": 1},
            "detected_info": {"private": False},
            "private_mode": False,
            "confirm_private_data_to_model": True,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["tavily_enabled"] is False
    assert len(auth_instances) == 1
    assert service_calls[0]["repo_url"] == "https://github.com/owner/private-repo"
    assert service_calls[0]["ref"].full_name == "owner/private-repo"
    assert service_calls[0]["system_score"] == {"score": 60}
    assert service_calls[0]["detected_info"] == {"private": True}
    assert service_calls[0]["private_mode"] is True
    assert auth_instances[0].create_installation_token_calls == [
        {
            "installation_id": "789",
            "repositories": ["private-repo"],
            "permissions": {
                "contents": "read",
                "metadata": "read",
                "pull_requests": "read",
                "actions": "read",
                "checks": "read",
                "administration": "read",
                "issues": "read",
                "deployments": "read",
                "repository_advisories": "read",
                "vulnerability_alerts": "read",
                "security_events": "read",
            },
        }
    ]
    assert created_clients[0].token == "installation-token"
    assert service_calls[0]["permissions"] == {
        "actions": "read",
        "checks": "read",
        "metadata": "read",
        "issues": "read",
        "deployments": "read",
        "vulnerability_alerts": "read",
        "administration": "write",
        "repository_advisories": "read",
        "security_events": "read",
        "secret_scanning_alerts": "none",
    }
    assert "installation-token" not in json.dumps(payload)
    with client.session_transaction() as session:
        assert "github_installation_token" not in session


def seed_completed_analysis(
    app,
    client,
    *,
    repo_url: str,
    private_mode: bool,
    system_score: dict,
    detected_info: dict,
    analysis_id: str = "analysis-1",
) -> str:
    with client.session_transaction() as session:
        owner_id = session.setdefault("analysis_owner_id", "owner-token")
    app.extensions.setdefault("repo_health_analysis_cache", {})[analysis_id] = {
        "owner_id": owner_id,
        "url": repo_url,
        "private_mode": private_mode,
        "system_score": system_score,
        "detected_info": detected_info,
    }
    with client.session_transaction() as session:
        session["last_analysis_id"] = analysis_id
    return analysis_id


def make_settings(
    model_configured: bool,
    github_configured: bool = False,
    tavily_api_key: str | None = None,
    github_api_base_url: str = "https://api.github.com",
) -> Settings:
    return Settings(
        flask_env="testing",
        flask_secret_key="test-secret-key",
        github_app_id="123" if github_configured else None,
        github_app_slug="repo-health" if github_configured else None,
        github_app_private_key_path=Path("secrets/github-app-private-key.pem") if github_configured else None,
        github_app_setup_url="http://127.0.0.1:5000/github-app/setup" if github_configured else None,
        tavily_api_key=tavily_api_key,
        model_base_url="https://model.example.test/v1" if model_configured else None,
        model_api_key="model-key" if model_configured else None,
        model_name="model-a" if model_configured else None,
        github_api_base_url=github_api_base_url,
    )
