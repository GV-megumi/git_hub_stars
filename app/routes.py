from __future__ import annotations

from dataclasses import asdict
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session

from app.agent.service import run_agent_analysis
from app.analyzer.collector import collect_repository_snapshot
from app.analyzer.scoring import score_repository
from app.errors import PermissionRequiredError, ValidationError
from app.github.app_auth import GithubAppAuth
from app.github.client import GithubClient
from app.github.url_parser import parse_github_repo_url

bp = Blueprint("main", __name__)

_ANALYSIS_SESSION_KEY = "last_analysis_id"
_ANALYSIS_OWNER_SESSION_KEY = "analysis_owner_id"
_ANALYSIS_CACHE_EXTENSION = "repo_health_analysis_cache"
_PRIVATE_ANALYSIS_PERMISSIONS = {
    "contents": "read",
    "metadata": "read",
    "pull_requests": "read",
}
_PRIVATE_AGENT_OPTIONAL_PERMISSIONS = (
    "actions",
    "administration",
    "checks",
    "deployments",
    "issues",
    "repository_advisories",
    "vulnerability_alerts",
    "security_events",
    "secret_scanning_alerts",
)

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


@bp.get("/")
def index():
    _analysis_owner_id()
    return render_template("index.html")


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
    analysis_id = uuid4().hex

    response_payload = {
        "analysis_id": analysis_id,
        "repository": asdict(snapshot.repo),
        "languages": snapshot.languages,
        "community": asdict(snapshot.community),
        "activity": asdict(snapshot.activity),
        "score": asdict(score),
        "partial_errors": snapshot.partial_errors,
        "private_mode": private_mode,
    }
    _store_analysis_result(analysis_id, repo_url=payload.get("url", ""), private_mode=private_mode, payload=response_payload)

    return jsonify(response_payload)


@bp.post("/api/agent/analyze")
def agent_analyze():
    settings = current_app.config["APP_SETTINGS"]
    if not settings.agent_configured:
        raise ValidationError("模型参数未配置，无法启动 AI 深度分析。")

    payload = _json_payload()
    analysis = _completed_analysis(payload)
    repo_url = analysis["url"]
    ref = parse_github_repo_url(repo_url)
    private_mode = bool(analysis["private_mode"])
    if private_mode:
        _require_private_model_confirmation(payload)
    system_score = analysis["system_score"]
    detected_info = analysis["detected_info"]

    permissions = session.get("github_installation_permissions", {}) if private_mode else {}
    if not isinstance(permissions, dict):
        permissions = {}
    token_permissions = _private_agent_token_permissions(permissions) if private_mode else None
    token = _private_installation_token(ref.repo, permissions=token_permissions) if private_mode else None
    github_client = GithubClient(base_url=settings.github_api_base_url, token=token)

    return jsonify(
        run_agent_analysis(
            repo_url=repo_url,
            ref=ref,
            system_score=system_score,
            detected_info=detected_info,
            private_mode=private_mode,
            settings=settings,
            github_client=github_client,
            permissions=permissions,
        )
    )


def _private_mode(payload: dict) -> bool:
    if "private_mode" not in payload:
        return False
    if not isinstance(payload["private_mode"], bool):
        raise ValidationError("private_mode must be a boolean.")
    return payload["private_mode"]


def _dict_payload_value(payload: dict, key: str) -> dict:
    value = payload.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValidationError(f"{key} must be a JSON object.")
    return value


def _store_analysis_result(analysis_id: str, *, repo_url: str, private_mode: bool, payload: dict) -> None:
    owner_id = _analysis_owner_id()
    session[_ANALYSIS_SESSION_KEY] = analysis_id
    _analysis_cache()[analysis_id] = {
        "owner_id": owner_id,
        "url": repo_url,
        "private_mode": private_mode,
        "system_score": payload["score"],
        "detected_info": {
            "repository": payload["repository"],
            "languages": payload["languages"],
            "community": payload["community"],
            "activity": payload["activity"],
            "partial_errors": payload["partial_errors"],
        },
    }


def _completed_analysis(payload: dict) -> dict:
    analysis_id = payload.get("analysis_id")
    if not isinstance(analysis_id, str) or not analysis_id:
        raise PermissionRequiredError("AI analysis requires a completed system analysis in this session.")
    analysis = _analysis_cache().get(analysis_id)
    if not isinstance(analysis, dict):
        raise PermissionRequiredError("Completed system analysis expired; please run system analysis again.")
    if analysis.get("owner_id") != session.get(_ANALYSIS_OWNER_SESSION_KEY):
        raise PermissionRequiredError("AI analysis requires a completed system analysis in this session.")

    repo_url = analysis.get("url")
    system_score = analysis.get("system_score")
    detected_info = analysis.get("detected_info")
    private_mode = analysis.get("private_mode")
    if not isinstance(repo_url, str) or not isinstance(system_score, dict) or not isinstance(detected_info, dict):
        raise PermissionRequiredError("Completed system analysis expired; please run system analysis again.")
    if not isinstance(private_mode, bool):
        raise PermissionRequiredError("Completed system analysis expired; please run system analysis again.")
    return {
        "url": repo_url,
        "private_mode": private_mode,
        "system_score": system_score,
        "detected_info": detected_info,
    }


def _analysis_cache() -> dict[str, dict]:
    cache = current_app.extensions.setdefault(_ANALYSIS_CACHE_EXTENSION, {})
    if not isinstance(cache, dict):
        current_app.extensions[_ANALYSIS_CACHE_EXTENSION] = {}
        return current_app.extensions[_ANALYSIS_CACHE_EXTENSION]
    return cache


def _analysis_owner_id() -> str:
    owner_id = session.get(_ANALYSIS_OWNER_SESSION_KEY)
    if not isinstance(owner_id, str) or not owner_id:
        owner_id = uuid4().hex
        session[_ANALYSIS_OWNER_SESSION_KEY] = owner_id
    return owner_id


def _require_private_model_confirmation(payload: dict) -> None:
    if payload.get("confirm_private_data_to_model") is not True:
        raise PermissionRequiredError(
            "Private repository AI analysis requires explicit confirmation before sending data to the model."
        )


def _private_installation_token(repo_name: str, permissions: dict[str, str] | None = None) -> str:
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
        permissions=permissions or _PRIVATE_ANALYSIS_PERMISSIONS.copy(),
    )
    token = token_response.get("token") if isinstance(token_response, dict) else None
    if not isinstance(token, str) or not token:
        raise ValidationError("GitHub App installation token response did not include a token.")
    return token


def _private_agent_token_permissions(granted_permissions: dict[str, str]) -> dict[str, str]:
    requested = _PRIVATE_ANALYSIS_PERMISSIONS.copy()
    for permission in _PRIVATE_AGENT_OPTIONAL_PERMISSIONS:
        if _permission_allows_read(granted_permissions.get(permission)):
            requested[permission] = "read"
    return requested


def _permission_allows_read(value: object) -> bool:
    return value in {"read", "write", "admin"}


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
    session.permanent = True
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
    _analysis_owner_id()
    settings = current_app.config["APP_SETTINGS"]
    installed = bool(session.get("github_installation_id"))
    return jsonify(
        {
            "configured": bool(settings.github_app_configured),
            "agent_configured": bool(settings.agent_configured),
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
    analysis_id = session.pop(_ANALYSIS_SESSION_KEY, None)
    owner_id = session.pop(_ANALYSIS_OWNER_SESSION_KEY, None)
    if isinstance(owner_id, str):
        _clear_analysis_cache_for_owner(owner_id)
    elif isinstance(analysis_id, str):
        _analysis_cache().pop(analysis_id, None)
    for key in _GITHUB_APP_SESSION_KEYS:
        session.pop(key, None)


def _clear_analysis_cache_for_owner(owner_id: str) -> None:
    cache = _analysis_cache()
    for analysis_id, analysis in list(cache.items()):
        if isinstance(analysis, dict) and analysis.get("owner_id") == owner_id:
            cache.pop(analysis_id, None)
