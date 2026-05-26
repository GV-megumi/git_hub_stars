from __future__ import annotations

import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.errors import (
    GithubApiError,
    GithubRateLimitError,
    NotFoundError,
    PermissionRequiredError,
    ValidationError,
)
from app.github.app_auth import GithubAppAuth


def test_build_install_url():
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=Path("missing.pem"),
    )

    assert auth.install_url() == "https://github.com/apps/repo-health/installations/new"


def test_app_jwt_can_be_verified_with_public_key_and_contains_issuer(tmp_path):
    private_pem, public_pem = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    auth = GithubAppAuth(app_slug="repo-health", app_id="123", private_key_path=key_path)
    now = int(time.time())

    token = auth.create_app_jwt()
    payload = jwt.decode(token, public_pem, algorithms=["RS256"], options={"verify_aud": False})

    assert payload["iss"] == "123"
    assert now - 90 <= payload["iat"] <= now
    assert now + 500 <= payload["exp"] <= now + 570


def test_create_installation_token_posts_expected_headers_repository_names_and_permissions(tmp_path, requests_mock):
    private_pem, public_pem = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    requests_mock.post(
        "https://api.example.test/app/installations/456/access_tokens",
        json={"token": "installation-token", "expires_at": "2026-05-26T12:00:00Z"},
    )
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test/",
    )

    result = auth.create_installation_token(
        "456",
        repositories=["repo"],
        permissions={"contents": "read", "metadata": "read"},
    )

    request = requests_mock.last_request
    assert result["token"] == "installation-token"
    assert request.timeout == 20
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert request.headers["User-Agent"] == "github-repo-health-tool"
    assert request.json() == {
        "repositories": ["repo"],
        "permissions": {"contents": "read", "metadata": "read"},
    }

    scheme, bearer_token = request.headers["Authorization"].split(" ", 1)
    assert scheme == "Bearer"
    payload = jwt.decode(bearer_token, public_pem, algorithms=["RS256"], options={"verify_aud": False})
    assert payload["iss"] == "123"


def test_create_installation_token_posts_default_read_only_permissions_when_omitted(tmp_path, requests_mock):
    private_pem, _ = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    requests_mock.post(
        "https://api.example.test/app/installations/456/access_tokens",
        json={"token": "installation-token"},
    )
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test",
    )

    auth.create_installation_token("456")

    assert requests_mock.last_request.json() == {
        "permissions": {"metadata": "read", "contents": "read"},
    }


def test_create_installation_token_rejects_non_numeric_installation_id(tmp_path):
    private_pem, _ = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test",
    )

    with pytest.raises(ValidationError):
        auth.create_installation_token("../456", repositories=["repo"])


def test_create_installation_token_rejects_full_repository_names(tmp_path):
    private_pem, _ = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test",
    )

    with pytest.raises(ValidationError):
        auth.create_installation_token("456", repositories=["owner/repo"])


@pytest.mark.parametrize("level", ["write", "admin", "triage"])
def test_create_installation_token_rejects_non_read_permission_levels(tmp_path, requests_mock, level):
    private_pem, _ = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    requests_mock.post(
        "https://api.example.test/app/installations/456/access_tokens",
        json={"token": "must-not-be-created"},
    )
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test",
    )

    with pytest.raises(ValidationError):
        auth.create_installation_token("456", permissions={"contents": level})
    assert requests_mock.call_count == 0


def test_get_installation_uses_app_jwt_and_returns_non_sensitive_installation_state(tmp_path, requests_mock):
    private_pem, public_pem = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    requests_mock.get(
        "https://api.example.test/app/installations/456",
        json={
            "id": 456,
            "repository_selection": "selected",
            "permissions": {"contents": "read"},
            "account": {"login": "octo-org", "type": "Organization", "id": 1},
            "repositories": [
                {"full_name": "octo-org/repo-one", "name": "repo-one"},
                {"name": "repo-two"},
                {"full_name": ""},
                "not-a-repository-object",
            ],
            "access_tokens_url": "https://api.github.com/app/installations/456/access_tokens",
        },
    )
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test",
    )

    result = auth.get_installation("456")

    request = requests_mock.last_request
    assert request.timeout == 20
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert result == {
        "id": 456,
        "repository_selection": "selected",
        "permissions": {"contents": "read"},
        "repositories": ["octo-org/repo-one", "repo-two"],
        "account": {"login": "octo-org", "type": "Organization", "id": 1},
    }
    scheme, bearer_token = request.headers["Authorization"].split(" ", 1)
    assert scheme == "Bearer"
    payload = jwt.decode(bearer_token, public_pem, algorithms=["RS256"], options={"verify_aud": False})
    assert payload["iss"] == "123"


def test_get_installation_rejects_non_numeric_installation_id(tmp_path):
    private_pem, _ = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test",
    )

    with pytest.raises(ValidationError):
        auth.get_installation("456/access_tokens")


@pytest.mark.parametrize(
    ("status_code", "github_message", "expected_error"),
    [
        (401, "Bad credentials", PermissionRequiredError),
        (403, "Resource not accessible by integration", PermissionRequiredError),
        (404, "Not Found", NotFoundError),
        (422, "Validation Failed", ValidationError),
        (500, "Server Error", GithubApiError),
    ],
)
def test_create_installation_token_maps_error_statuses(tmp_path, requests_mock, status_code, github_message, expected_error):
    private_pem, _ = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    requests_mock.post(
        "https://api.example.test/app/installations/456/access_tokens",
        status_code=status_code,
        json={"message": github_message},
    )
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test",
    )

    with pytest.raises(expected_error) as exc_info:
        auth.create_installation_token("456")

    error = exc_info.value
    assert f"HTTP {status_code}" in error.message
    assert error.github_status_code == status_code
    assert error.github_path == "/app/installations/456/access_tokens"
    assert error.github_message == github_message


def test_create_installation_token_maps_rate_limited_responses(tmp_path, requests_mock):
    private_pem, _ = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    requests_mock.post(
        "https://api.example.test/app/installations/456/access_tokens",
        status_code=403,
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1770000000"},
        json={"message": "API rate limit exceeded"},
    )
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test",
    )

    with pytest.raises(GithubRateLimitError) as exc_info:
        auth.create_installation_token("456")

    error = exc_info.value
    assert error.github_status_code == 403
    assert error.github_path == "/app/installations/456/access_tokens"
    assert error.github_message == "API rate limit exceeded"
    assert error.rate_limit_remaining == "0"
    assert error.rate_limit_reset == "1770000000"


def test_create_installation_token_maps_429_to_rate_limit(tmp_path, requests_mock):
    private_pem, _ = generate_test_key_pair()
    key_path = tmp_path / "app-private-key.pem"
    key_path.write_text(private_pem, encoding="utf-8")
    requests_mock.post(
        "https://api.example.test/app/installations/456/access_tokens",
        status_code=429,
        headers={"Retry-After": "10"},
        json={"message": "Too Many Requests"},
    )
    auth = GithubAppAuth(
        app_slug="repo-health",
        app_id="123",
        private_key_path=key_path,
        api_base_url="https://api.example.test",
    )

    with pytest.raises(GithubRateLimitError) as exc_info:
        auth.create_installation_token("456")

    assert exc_info.value.github_status_code == 429
    assert exc_info.value.retry_after == "10"


def generate_test_key_pair() -> tuple[str, str]:
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
