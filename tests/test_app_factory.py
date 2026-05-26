from __future__ import annotations

import importlib
import sys

from flask import Flask

from app import create_app
from app.config import Settings


def test_app_factory_registers_health_route():
    app = create_app(make_settings())
    client = app.test_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_run_module_exposes_flask_app(monkeypatch):
    monkeypatch.setattr("app.config.Settings.from_env", staticmethod(make_settings))
    sys.modules.pop("run", None)
    run = importlib.import_module("run")

    assert isinstance(run.app, Flask)
    response = run.app.test_client().get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def make_settings() -> Settings:
    return Settings(
        flask_env="testing",
        flask_secret_key="test-secret-key",
        github_app_id=None,
        github_app_slug=None,
        github_app_private_key_path=None,
        github_app_setup_url=None,
        tavily_api_key=None,
        model_base_url=None,
        model_api_key=None,
        model_name=None,
        github_api_base_url="https://api.github.com",
    )
