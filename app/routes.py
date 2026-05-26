from __future__ import annotations

from dataclasses import asdict

from flask import Blueprint, current_app, jsonify, redirect, request, session

from app.analyzer.collector import collect_repository_snapshot
from app.analyzer.scoring import score_repository
from app.errors import PermissionRequiredError, ValidationError
from app.github.app_auth import GithubAppAuth
from app.github.client import GithubClient
from app.github.url_parser import parse_github_repo_url

bp = Blueprint("main", __name__)

_PRIVATE_ANALYSIS_PERMISSIONS = {"contents": "read", "metadata": "read"}

_GITHUB_APP_SESSION_KEYS = (
    "github_installation_id",
    "github_app_setup_action",
    "github_repository_selection",
    "github_repositories",
    "github_installation_permissions",
    "github_installation_account",
    "github_installation_token",
    "github_app_private_key_path",
)


@bp.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@bp.post("/api/analyze")
def analyze_repository():
    payload = _json_payload()
    ref = parse_github_repo_url(payload.get("url", ""))
    private_mode = _private_mode(payload)
    settings = current_app.config["APP_SETTINGS"]
    token = _private_installation_token(ref.repo) if private_mode else None
    client = GithubClient(base_url=settings.github_api_base_url, token=token)
    snapshot = collect_repository_snapshot(client, ref)
    score = score_repository(snapshot)

    return jsonify(
        {
            "repository": asdict(snapshot.repo),
            "languages": snapshot.languages,
            "community": asdict(snapshot.community),
            "activity": asdict(snapshot.activity),
            "score": asdict(score),
            "partial_errors": snapshot.partial_errors,
            "private_mode": private_mode,
        }
    )


def _private_mode(payload: dict) -> bool:
    if "private_mode" not in payload:
        return False
    if not isinstance(payload["private_mode"], bool):
        raise ValidationError("private_mode must be a boolean.")
    return payload["private_mode"]


def _private_installation_token(repo_name: str) -> str:
    installation_id = session.get("github_installation_id")
    if not installation_id:
        raise PermissionRequiredError("GitHub App installation is required for private repository analysis.")

    settings = current_app.config["APP_SETTINGS"]
    if not settings.github_app_configured:
        raise ValidationError("GitHub App is not configured; private repositories require GitHub App access.")

    auth = GithubAppAuth(
        app_slug=settings.github_app_slug,
        app_id=settings.github_app_id,
        private_key_path=settings.github_app_private_key_path,
        api_base_url=settings.github_api_base_url,
    )
    token_response = auth.create_installation_token(
        installation_id,
        repositories=[repo_name],
        permissions=_PRIVATE_ANALYSIS_PERMISSIONS.copy(),
    )
    token = token_response.get("token") if isinstance(token_response, dict) else None
    if not isinstance(token, str) or not token:
        raise ValidationError("GitHub App installation token response did not include a token.")
    return token


@bp.get("/github-app/install")
def github_app_install():
    settings = current_app.config["APP_SETTINGS"]
    if not settings.github_app_configured:
        raise ValidationError("GitHub App is not configured; public repositories can still be analyzed anonymously.")

    auth = GithubAppAuth(
        app_slug=settings.github_app_slug,
        app_id=settings.github_app_id,
        private_key_path=settings.github_app_private_key_path,
        api_base_url=settings.github_api_base_url,
    )
    return redirect(auth.install_url())


@bp.get("/github-app/setup")
def github_app_setup():
    settings = current_app.config["APP_SETTINGS"]
    if not settings.github_app_configured:
        raise ValidationError("GitHub App is not configured; public repositories can still be analyzed anonymously.")

    installation_id = request.args.get("installation_id")
    if not installation_id:
        raise ValidationError("GitHub App setup callback is missing installation_id.")
    installation_id = _numeric_installation_id(installation_id)

    setup_action = request.args.get("setup_action")
    if setup_action == "":
        setup_action = None
    if setup_action not in {None, "install", "update"}:
        raise ValidationError("GitHub App setup_action must be install or update.")

    auth = GithubAppAuth(
        app_slug=settings.github_app_slug,
        app_id=settings.github_app_id,
        private_key_path=settings.github_app_private_key_path,
        api_base_url=settings.github_api_base_url,
    )
    installation = auth.get_installation(installation_id)

    _clear_github_app_session()
    session["github_installation_id"] = installation_id
    repository_selection = installation.get("repository_selection")
    repositories = installation.get("repositories") or []

    if setup_action:
        session["github_app_setup_action"] = setup_action
    if repository_selection:
        session["github_repository_selection"] = repository_selection
    if repositories:
        session["github_repositories"] = repositories
    session["github_installation_permissions"] = installation.get("permissions") or {}
    session["github_installation_account"] = installation.get("account")

    return redirect("/")


@bp.post("/github-app/clear")
def github_app_clear():
    _clear_github_app_session()
    return jsonify({"installed": False})


@bp.get("/api/github-app/session")
def github_app_session():
    settings = current_app.config["APP_SETTINGS"]
    installed = bool(session.get("github_installation_id"))
    return jsonify(
        {
            "configured": bool(settings.github_app_configured),
            "installed": installed,
            "installation_id": installed,
            "setup_action": session.get("github_app_setup_action"),
            "repository_selection": session.get("github_repository_selection"),
            "repositories": session.get("github_repositories", []),
            "permissions": session.get("github_installation_permissions", {}),
            "account": session.get("github_installation_account"),
        }
    )


def _numeric_installation_id(value: str) -> str:
    if not value.isdecimal():
        raise ValidationError("GitHub App installation_id must be numeric.")
    return value


def _json_payload() -> dict:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    return payload


def _clear_github_app_session() -> None:
    for key in _GITHUB_APP_SESSION_KEYS:
        session.pop(key, None)
