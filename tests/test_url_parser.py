import pytest

from app.errors import ValidationError
from app.github.url_parser import parse_github_repo_url


@pytest.mark.parametrize(
    ("url", "owner", "repo"),
    [
        ("https://github.com/fastapi/fastapi", "fastapi", "fastapi"),
        ("https://github.com/pallets/flask.git", "pallets", "flask"),
        ("https://www.github.com/psf/requests/", "psf", "requests"),
    ],
)
def test_parse_valid_github_url(url, owner, repo):
    result = parse_github_repo_url(url)

    assert result.owner == owner
    assert result.repo == repo
    assert result.full_name == f"{owner}/{repo}"


@pytest.mark.parametrize(
    "url",
    [
        None,
        123,
        "",
        "http://github.com/owner/repo",
        "https://gitlab.com/a/b",
        "https://[::1/owner/repo",
        "https://github.com/a",
        "https://github.com/-owner/repo",
        "https://github.com/owner-/repo",
        "https://github.com/owner/re po",
        "https://github.com/owner/re\tpo",
        "https://github.com/owner/re\npo",
        "https://github.com/owner/re\rpo",
        "https://github.com/owner/repo%2Fissues",
        "https://github.com/owner/.",
        "https://github.com/owner/..",
        "https://github.com/owner//repo",
        "https://github.com//owner/repo",
        "https://github.com/a/b/issues",
        "https://github.com/owner/repo;foo",
        "https://github.com/owner/repo;",
        "https://github.com/owner/repo?",
        "https://github.com/owner/repo#",
        "https://github.com/owner/repo?tab=readme",
        "https://github.com/owner/repo#readme",
        "not-a-url",
    ],
)
def test_reject_invalid_repo_url(url):
    with pytest.raises(ValidationError):
        parse_github_repo_url(url)
