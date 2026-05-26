from __future__ import annotations

from pathlib import Path

from app import create_app
from app.config import Settings


def test_index_route_renders_frontend_shell():
    app = create_app(make_settings())
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "GitHub 仓库体检" in html
    assert 'href="/static/css/styles.css"' in html
    assert 'src="/static/js/app.js"' in html

    expected_dom_ids = [
        "repo-form",
        "repo-url",
        "mode-public",
        "mode-private",
        "github-app-status",
        "github-app-badge",
        "github-app-detail",
        "github-app-meta",
        "github-app-install",
        "github-app-clear",
        "score-value",
        "score-status",
        "repo-name",
        "repo-description",
        "metrics-grid",
        "risk-list",
        "recommendation-list",
        "partial-errors-list",
        "agent-note",
        "agent-button",
        "language-chart",
        "score-chart",
    ]
    for dom_id in expected_dom_ids:
        assert f'id="{dom_id}"' in html

    assert "公开模式" in html
    assert "私有模式" in html
    assert "GitHub App 授权" in html
    assert "Agent 分析" in html

    assert html.count("<canvas") == 2


def test_frontend_static_assets_are_served():
    app = create_app(make_settings())
    client = app.test_client()

    css = client.get("/static/css/styles.css")
    js = client.get("/static/js/app.js")

    assert css.status_code == 200
    assert js.status_code == 200


def test_static_javascript_contains_reset_and_clear_safety_logic():
    js = Path("static/js/app.js").read_text(encoding="utf-8")

    assert "function resetAnalysisState" in js
    assert "state.lastAnalysis = null" in js
    assert "renderInitialState()" in js
    assert "clearGithubAppSession" in js
    assert "loadGithubAppSession" in js
    assert "state.githubApp = null" in js
    assert 'els["github-app-clear"].disabled = true' in js


def test_static_javascript_renders_complete_community_checklist():
    js = Path("static/js/app.js").read_text(encoding="utf-8")

    for label in [
        "README",
        "License",
        "CONTRIBUTING",
        "Code of Conduct",
        "Security Policy",
        "Issue Template",
        "PR Template",
        "缺失",
    ]:
        assert label in js

    for alias in [
        "security",
        "security_policy",
        "security_policy_file",
        "pull_request_template",
        "pr_template",
    ]:
        assert alias in js


def make_settings() -> Settings:
    return Settings(
        flask_env="testing",
        flask_secret_key="test-secret-key",
        github_app_id=None,
        github_app_slug=None,
        github_app_private_key_path=Path("secrets/github-app-private-key.pem"),
        github_app_setup_url=None,
        tavily_api_key=None,
        model_base_url=None,
        model_api_key=None,
        model_name=None,
    )
