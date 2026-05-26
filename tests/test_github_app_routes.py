from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import create_app
from app.config import Settings


def test_install_route_requires_configured_github_app():
    app = create_app(make_settings())
    client = app.test_client()

    response = client.get("/github-app/install")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"] == "validation_error"
    assert "GitHub App" in payload["message"]


def test_configured_install_route_redirects_to_github_app_installation_url():
    app = create_app(make_settings(configured=True))
    client = app.test_client()

    response = client.get("/github-app/install")

    assert response.status_code == 302
    assert response.headers["Location"] == "https://github.com/apps/repo-health/installations/new"


def test_setup_requires_installation_id():
    app = create_app(make_settings(configured=True))
    client = app.test_client()

    response = client.get("/github-app/setup")

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_setup_requires_configured_github_app():
    app = create_app(make_settings())
    client = app.test_client()

    response = client.get("/github-app/setup?installation_id=789")

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


@pytest.mark.parametrize("installation_id", ["abc", "../789", "789/access_tokens"])
def test_setup_rejects_non_numeric_installation_id(installation_id):
    app = create_app(make_settings(configured=True))
    client = app.test_client()

    response = client.get(f"/github-app/setup?installation_id={installation_id}")

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_setup_rejects_unknown_setup_action():
    app = create_app(make_settings(configured=True))
    client = app.test_client()

    response = client.get("/github-app/setup?installation_id=789&setup_action=delete")

    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_setup_verifies_installation_resets_old_session_and_exposes_non_sensitive_state(monkeypatch):
    app = create_app(make_settings(configured=True))
    client = app.test_client()
    fake_auth = install_fake_auth(monkeypatch, repositories=["octo-org/repo-one", "repo-two"])

    initial = client.get("/api/github-app/session")
    assert initial.status_code == 200
    assert initial.get_json() == {
        "configured": True,
        "agent_configured": False,
        "installed": False,
        "installation_id": False,
        "repository_selection": None,
        "repositories": [],
        "setup_action": None,
        "permissions": {},
        "account": None,
    }

    with client.session_transaction() as session:
        session["github_installation_id"] = "old"
        session["github_app_setup_action"] = "update"
        session["github_repository_selection"] = "all"
        session["github_repositories"] = ["old/repo"]
        session["github_installation_permissions"] = {"contents": "read"}
        session["github_installation_account"] = {"login": "old-org"}
        session["github_installation_token"] = "secret-token"
        session["github_app_private_key_path"] = "secret.pem"
        session["last_analysis_id"] = "old-analysis"
        session["analysis_owner_id"] = "owner-token"
    app.extensions.setdefault("repo_health_analysis_cache", {})["old-analysis"] = {
        "owner_id": "owner-token",
        "private": "summary",
    }
    app.extensions["repo_health_analysis_cache"]["other-analysis"] = {
        "owner_id": "other-owner",
        "private": "summary",
    }

    setup = client.get(
        "/github-app/setup"
        "?installation_id=789"
        "&setup_action=install"
        "&repository_selection=selected"
        "&repositories=evil%2Frepo"
    )

    assert setup.status_code == 302
    assert setup.headers["Location"] == "/"
    assert fake_auth.get_installation_calls == ["789"]
    with client.session_transaction() as session:
        assert session["github_installation_id"] == "789"
        assert session["github_app_setup_action"] == "install"
        assert session["github_repository_selection"] == "selected"
        assert session["github_repositories"] == ["octo-org/repo-one", "repo-two"]
        assert session["github_installation_permissions"] == {"contents": "read", "metadata": "read"}
        assert session["github_installation_account"] == {
            "login": "octo-org",
            "type": "Organization",
            "id": 1,
        }
        assert "github_installation_token" not in session
        assert "github_app_private_key_path" not in session
        assert "last_analysis_id" not in session
        assert "analysis_owner_id" not in session
    assert "old-analysis" not in app.extensions["repo_health_analysis_cache"]
    assert "other-analysis" in app.extensions["repo_health_analysis_cache"]

    status = client.get("/api/github-app/session")

    payload = status.get_json()
    assert payload["configured"] is True
    assert payload["agent_configured"] is False
    assert payload["installed"] is True
    assert payload["installation_id"] is True
    assert payload["setup_action"] == "install"
    assert payload["repository_selection"] == "selected"
    assert payload["repositories"] == ["octo-org/repo-one", "repo-two"]
    assert payload["permissions"] == {"contents": "read", "metadata": "read"}
    assert payload["account"] == {"login": "octo-org", "type": "Organization", "id": 1}
    serialized_payload = json.dumps(payload).lower()
    assert "token" not in serialized_payload
    assert "private" not in serialized_payload
    assert "secret" not in serialized_payload

    cleared = client.post("/github-app/clear")

    assert cleared.status_code == 200
    assert cleared.get_json() == {"installed": False}
    with client.session_transaction() as session:
        assert "github_installation_id" not in session
        assert "github_app_setup_action" not in session
        assert "github_repository_selection" not in session
        assert "github_repositories" not in session
        assert "github_installation_permissions" not in session
        assert "github_installation_account" not in session
        assert "github_installation_token" not in session
        assert "github_app_private_key_path" not in session
    assert client.get("/api/github-app/session").get_json()["installed"] is False


def test_setup_without_repository_params_clears_old_repositories(monkeypatch):
    app = create_app(make_settings(configured=True))
    client = app.test_client()
    install_fake_auth(monkeypatch, repository_selection="all")
    with client.session_transaction() as session:
        session["github_repositories"] = ["old/repo"]

    response = client.get("/github-app/setup?installation_id=789")

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert "github_repositories" not in session
        assert session["github_repository_selection"] == "all"
    assert client.get("/api/github-app/session").get_json()["repositories"] == []


def test_setup_ignores_spoofed_repository_query_scope(monkeypatch):
    app = create_app(make_settings(configured=True))
    client = app.test_client()
    install_fake_auth(monkeypatch, repository_selection="all", repositories=["octo-org/api-state"])

    response = client.get(
        "/github-app/setup"
        "?installation_id=789"
        "&repository_selection=owned"
        "&repositories=evil%2Frepo"
    )

    assert response.status_code == 302
    with client.session_transaction() as session:
        assert session["github_repository_selection"] == "all"
        assert session["github_repositories"] == ["octo-org/api-state"]
    payload = client.get("/api/github-app/session").get_json()
    assert payload["repository_selection"] == "all"
    assert payload["repositories"] == ["octo-org/api-state"]


def install_fake_auth(monkeypatch, repository_selection: str = "selected", repositories: list[str] | None = None):
    from app import routes

    class FakeGithubAppAuth:
        get_installation_calls: list[str] = []

        def __init__(self, app_slug, app_id, private_key_path, api_base_url="https://api.github.com"):
            self.app_slug = app_slug
            self.app_id = app_id
            self.private_key_path = private_key_path
            self.api_base_url = api_base_url

        def get_installation(self, installation_id):
            self.get_installation_calls.append(installation_id)
            return {
                "id": int(installation_id),
                "repository_selection": repository_selection,
                "permissions": {"contents": "read", "metadata": "read"},
                "repositories": repositories or [],
                "account": {"login": "octo-org", "type": "Organization", "id": 1},
            }

    monkeypatch.setattr(routes, "GithubAppAuth", FakeGithubAppAuth)
    return FakeGithubAppAuth


def make_settings(configured: bool = False) -> Settings:
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
    )
