from __future__ import annotations

from flask import Flask, jsonify

from app.config import DEFAULT_FLASK_SECRET_KEY, Settings
from app.errors import AppError


def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__, static_folder="../static", template_folder="../templates")
    app_settings = settings or Settings.from_env()
    _validate_session_secret(app_settings)
    app.config["APP_SETTINGS"] = app_settings
    app.secret_key = app_settings.flask_secret_key

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        return jsonify(error.to_dict()), error.status_code

    from app.routes import bp

    app.register_blueprint(bp)
    return app


def _validate_session_secret(settings: Settings) -> None:
    if settings.github_app_configured and settings.flask_secret_key == DEFAULT_FLASK_SECRET_KEY:
        raise RuntimeError("FLASK_SECRET_KEY must be set to a strong non-default value when GitHub App is configured.")
