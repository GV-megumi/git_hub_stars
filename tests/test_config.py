from app import create_app
from app.config import Settings
from app.errors import AppError


def test_settings_defaults_allow_public_mode(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "")
    monkeypatch.setenv("GITHUB_APP_SLUG", "")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", "")
    monkeypatch.setenv("GITHUB_APP_SETUP_URL", "")
    monkeypatch.setenv("MODEL_BASE_URL", "")
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("MODEL_NAME", "")
    monkeypatch.setenv("FLASK_SECRET_KEY", "")

    settings = Settings.from_env()

    assert settings.github_app_configured is False
    assert settings.agent_configured is False
    assert settings.flask_secret_key
    assert settings.github_api_base_url == "https://api.github.com"


def test_github_app_config_requires_all_values(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_SLUG", "repo-health")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", "secrets/private-key.pem")
    monkeypatch.setenv("GITHUB_APP_SETUP_URL", "http://127.0.0.1:5000/github-app/setup")

    settings = Settings.from_env()

    assert settings.github_app_configured is True


def test_create_app_rejects_default_secret_when_github_app_is_configured(monkeypatch):
    monkeypatch.setenv("FLASK_SECRET_KEY", "")
    monkeypatch.setenv("GITHUB_APP_ID", "123")
    monkeypatch.setenv("GITHUB_APP_SLUG", "repo-health")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", "secrets/private-key.pem")
    monkeypatch.setenv("GITHUB_APP_SETUP_URL", "http://127.0.0.1:5000/github-app/setup")

    settings = Settings.from_env()

    try:
        create_app(settings)
    except RuntimeError as exc:
        assert "FLASK_SECRET_KEY" in str(exc)
    else:
        raise AssertionError("GitHub App mode must not run with the development Flask secret key")


def test_agent_config_requires_all_model_values(monkeypatch):
    monkeypatch.setenv("MODEL_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("MODEL_API_KEY", "key")
    monkeypatch.setenv("MODEL_NAME", "model-a")

    settings = Settings.from_env()

    assert settings.agent_configured is True


def test_create_app_registers_health_route_and_settings():
    settings = Settings.from_env()
    app = create_app(settings)

    assert app.config["APP_SETTINGS"] is settings
    assert app.secret_key == settings.flask_secret_key

    response = app.test_client().get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_create_app_serializes_app_error_as_json():
    app = create_app(Settings.from_env())

    @app.get("/raise-app-error")
    def raise_app_error():
        raise AppError("example failure")

    response = app.test_client().get("/raise-app-error")

    assert response.status_code == 400
    assert response.get_json() == {"error": "app_error", "message": "example failure"}
