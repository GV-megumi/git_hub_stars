import pytest

from app.errors import (
    GithubApiError,
    GithubRateLimitError,
    NotFoundError,
    PermissionRequiredError,
    ValidationError,
)
from app.github.client import GithubClient


def test_get_json_uses_required_headers_and_returns_json(requests_mock):
    requests_mock.get(
        "https://api.github.com/repos/fastapi/fastapi",
        json={"full_name": "fastapi/fastapi", "stargazers_count": 1},
    )
    client = GithubClient(base_url="https://api.github.com", token=None)

    data = client.get_json("/repos/fastapi/fastapi")

    assert data["full_name"] == "fastapi/fastapi"
    request = requests_mock.last_request
    assert request.headers["Accept"] == "application/vnd.github+json"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert request.headers["User-Agent"] == "github-repo-health-tool"
    assert "Authorization" not in request.headers


def test_get_json_sends_token_header_when_token_exists(requests_mock):
    requests_mock.get("https://api.github.com/repos/a/private", json={"full_name": "a/private"})
    client = GithubClient(base_url="https://api.github.com", token="installation-token")

    client.get_json("/repos/a/private")

    assert requests_mock.last_request.headers["Authorization"] == "Bearer installation-token"


def test_get_json_passes_params_and_handles_base_url_trailing_slash(requests_mock):
    requests_mock.get("https://api.github.test/repos/a/repo/issues", json=[{"number": 1}])
    client = GithubClient(base_url="https://api.github.test/", token=None)

    data = client.get_json("/repos/a/repo/issues", params={"state": "open", "per_page": 10})

    assert data == [{"number": 1}]
    assert requests_mock.last_request.qs == {"state": ["open"], "per_page": ["10"]}


def test_get_json_uses_20_second_timeout(requests_mock):
    requests_mock.get("https://api.github.com/repos/a/repo", json={"full_name": "a/repo"})
    client = GithubClient(base_url="https://api.github.com", token=None)

    client.get_json("/repos/a/repo")

    assert requests_mock.last_request.timeout == 20


def test_get_json_returns_status_payload_for_202_no_content(requests_mock):
    requests_mock.get(
        "https://api.github.com/repos/a/repo/dependency-graph/sbom/fetch-report/1",
        status_code=202,
        text="",
    )
    client = GithubClient()

    data = client.get_json(
        "/repos/a/repo/dependency-graph/sbom/fetch-report/1",
        allow_redirects=False,
    )

    assert data == {"status_code": 202}


def test_get_json_returns_redirect_location_for_302(requests_mock):
    requests_mock.get(
        "https://api.github.com/repos/a/repo/dependency-graph/sbom/fetch-report/1",
        status_code=302,
        headers={"Location": "https://codeload.github.com/private-sbom"},
    )
    client = GithubClient()

    data = client.get_json(
        "/repos/a/repo/dependency-graph/sbom/fetch-report/1",
        allow_redirects=False,
    )

    assert data == {"status_code": 302}


def test_get_json_returns_status_payload_for_204_no_content(requests_mock):
    requests_mock.get("https://api.github.com/repos/a/repo/empty", status_code=204)
    client = GithubClient()

    data = client.get_json("/repos/a/repo/empty")

    assert data == {"status_code": 204}


def test_404_raises_not_found(requests_mock):
    requests_mock.get("https://api.github.com/repos/a/missing", status_code=404, json={})
    client = GithubClient()

    with pytest.raises(NotFoundError):
        client.get_json("/repos/a/missing")


def test_403_rate_limit_raises_rate_limit_error_with_context(requests_mock):
    requests_mock.get(
        "https://api.github.com/repos/a/repo",
        status_code=403,
        json={"message": "API rate limit exceeded for user."},
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1770000000"},
    )
    client = GithubClient()

    with pytest.raises(GithubRateLimitError) as exc_info:
        client.get_json("/repos/a/repo")

    payload = exc_info.value.to_dict()
    assert payload["error"] == "github_rate_limit"
    assert payload["github_status_code"] == 403
    assert payload["github_path"] == "/repos/a/repo"
    assert payload["github_message"] == "API rate limit exceeded for user."
    assert payload["rate_limit_remaining"] == "0"
    assert payload["rate_limit_reset"] == "1770000000"


def test_429_rate_limit_raises_rate_limit_error_with_retry_after(requests_mock):
    requests_mock.get(
        "https://api.github.com/repos/a/repo",
        status_code=429,
        json={"message": "Too many requests"},
        headers={"Retry-After": "60", "X-RateLimit-Reset": "1770000000"},
    )
    client = GithubClient()

    with pytest.raises(GithubRateLimitError) as exc_info:
        client.get_json("/repos/a/repo")

    payload = exc_info.value.to_dict()
    assert exc_info.value.status_code == 429
    assert payload["github_status_code"] == 429
    assert payload["github_path"] == "/repos/a/repo"
    assert payload["github_message"] == "Too many requests"
    assert payload["retry_after"] == "60"
    assert payload["rate_limit_reset"] == "1770000000"


def test_403_secondary_rate_limit_with_retry_after_raises_rate_limit_error(requests_mock):
    requests_mock.get(
        "https://api.github.com/repos/a/repo",
        status_code=403,
        json={"message": "You have exceeded a secondary rate limit."},
        headers={"Retry-After": "30"},
    )
    client = GithubClient()

    with pytest.raises(GithubRateLimitError) as exc_info:
        client.get_json("/repos/a/repo")

    payload = exc_info.value.to_dict()
    assert payload["github_status_code"] == 403
    assert payload["github_message"] == "You have exceeded a secondary rate limit."
    assert payload["retry_after"] == "30"


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_errors_raise_permission_required(requests_mock, status_code):
    requests_mock.get("https://api.github.com/repos/a/private", status_code=status_code, json={})
    client = GithubClient()

    with pytest.raises(PermissionRequiredError):
        client.get_json("/repos/a/private")


def test_403_permission_error_preserves_response_context(requests_mock):
    requests_mock.get(
        "https://api.github.com/repos/a/private",
        status_code=403,
        json={"message": "Resource not accessible by integration"},
    )
    client = GithubClient()

    with pytest.raises(PermissionRequiredError) as exc_info:
        client.get_json("/repos/a/private")

    payload = exc_info.value.to_dict()
    assert payload["error"] == "permission_required"
    assert payload["github_status_code"] == 403
    assert payload["github_path"] == "/repos/a/private"
    assert payload["github_message"] == "Resource not accessible by integration"


def test_404_preserves_response_context(requests_mock):
    requests_mock.get(
        "https://api.github.com/repos/a/missing",
        status_code=404,
        json={"message": "Not Found"},
    )
    client = GithubClient()

    with pytest.raises(NotFoundError) as exc_info:
        client.get_json("/repos/a/missing")

    payload = exc_info.value.to_dict()
    assert payload["error"] == "not_found"
    assert payload["github_status_code"] == 404
    assert payload["github_path"] == "/repos/a/missing"
    assert payload["github_message"] == "Not Found"


@pytest.mark.parametrize(
    ("status_code", "github_message"),
    [(422, "Validation Failed"), (500, "Server Error")],
)
def test_github_api_error_preserves_response_context(requests_mock, status_code, github_message):
    requests_mock.get(
        "https://api.github.com/repos/a/repo",
        status_code=status_code,
        json={"message": github_message},
    )
    client = GithubClient()

    with pytest.raises(GithubApiError) as exc_info:
        client.get_json("/repos/a/repo")

    payload = exc_info.value.to_dict()
    assert payload["error"] == "github_api_error"
    assert payload["github_status_code"] == status_code
    assert payload["github_path"] == "/repos/a/repo"
    assert payload["github_message"] == github_message
    assert github_message in payload["message"]


@pytest.mark.parametrize("status_code", [400, 422, 500])
def test_other_error_statuses_raise_github_api_error(requests_mock, status_code):
    requests_mock.get("https://api.github.com/repos/a/repo", status_code=status_code, json={})
    client = GithubClient()

    with pytest.raises(GithubApiError):
        client.get_json("/repos/a/repo")


def test_get_json_rejects_path_without_leading_slash():
    client = GithubClient()

    with pytest.raises(ValidationError):
        client.get_json("repos/a/b")


@pytest.mark.parametrize(
    "path",
    [
        "//api.github.com/repos/a/b",
        "https://api.github.com/repos/a/b",
        "/repos/a/ b",
        "/repos/a\nb",
        "/repos/a\x00b",
    ],
)
def test_get_json_rejects_malformed_internal_paths(path):
    client = GithubClient()

    with pytest.raises(ValidationError):
        client.get_json(path)
