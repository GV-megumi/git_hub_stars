import pytest

from app.agent.tools import GithubAgentTools
from app.errors import NotFoundError, PermissionRequiredError
from app.github.url_parser import RepoRef


class FakeClient:
    def __init__(self, fixtures=None, errors=None):
        self.calls = []
        self.fixtures = fixtures or {}
        self.errors = errors or {}

    def get_json(self, path, params=None):
        self.calls.append((path, params))
        if path in self.errors:
            raise self.errors[path]
        fixtures = {
            "/repos/owner/repo": {
                "full_name": "owner/repo",
                "stargazers_count": 10,
                "forks_count": 2,
                "open_issues_count": 4,
                "archived": False,
                "fork": False,
                "default_branch": "main",
                "license": {"spdx_id": "MIT", "name": "MIT License"},
            },
            "/repos/owner/repo/languages": {"Python": 900, "HTML": 100},
            "/repos/owner/repo/releases": [
                {
                    "tag_name": "v1.0.0",
                    "name": "Version 1",
                    "published_at": "2026-05-01T00:00:00Z",
                    "prerelease": False,
                    "draft": False,
                    "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
                }
            ],
            "/repos/owner/repo/actions/runs": {
                "total_count": 2,
                "workflow_runs": [
                    {
                        "id": 1,
                        "name": "CI",
                        "status": "completed",
                        "conclusion": "success",
                        "event": "push",
                        "created_at": "2026-05-01T00:00:00Z",
                        "updated_at": "2026-05-01T00:01:00Z",
                        "html_url": "https://github.com/owner/repo/actions/runs/1",
                    },
                    {
                        "id": 2,
                        "name": "CI",
                        "status": "completed",
                        "conclusion": "failure",
                        "event": "pull_request",
                        "created_at": "2026-05-02T00:00:00Z",
                        "updated_at": "2026-05-02T00:01:00Z",
                        "html_url": "https://github.com/owner/repo/actions/runs/2",
                    },
                ],
            },
        }
        fixtures.update(self.fixtures)
        return fixtures[path]


def make_tools(private_mode=False, permissions=None, fixtures=None, errors=None):
    client = FakeClient(fixtures=fixtures, errors=errors)
    tools = GithubAgentTools(
        client,
        RepoRef("owner", "repo"),
        private_mode=private_mode,
        permissions={} if permissions is None else permissions,
    )
    return tools, client


def test_get_repo_summary_returns_bounded_repository_fields():
    tools, client = make_tools(private_mode=False)

    result = tools.get_repo_summary()

    assert result == {
        "full_name": "owner/repo",
        "stars": 10,
        "forks": 2,
        "open_issues": 4,
        "archived": False,
        "fork": False,
        "default_branch": "main",
        "license": "MIT",
        "source": "https://github.com/owner/repo",
    }
    assert client.calls == [("/repos/owner/repo", None)]


def test_get_language_breakdown_returns_percentages_sorted_by_bytes():
    tools, client = make_tools(private_mode=True)

    result = tools.get_language_breakdown()

    assert result == {
        "total_bytes": 1000,
        "languages": [
            {"name": "Python", "bytes": 900, "percentage": 90.0},
            {"name": "HTML", "bytes": 100, "percentage": 10.0},
        ],
    }
    assert client.calls == [("/repos/owner/repo/languages", None)]


def test_get_releases_returns_bounded_summary_and_drops_large_nested_fields():
    tools, client = make_tools(
        fixtures={
            "/repos/owner/repo/releases": [
                {
                    "tag_name": "v1.0.0",
                    "name": "Version 1",
                    "published_at": "2026-05-01T00:00:00Z",
                    "prerelease": False,
                    "draft": False,
                    "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
                    "body": "long release notes",
                    "assets": [{"name": "build.zip"}],
                    "author": {"login": "octocat"},
                }
            ]
        }
    )

    result = tools.get_releases()

    assert result == {
        "available": True,
        "count": 1,
        "items": [
            {
                "tag_name": "v1.0.0",
                "name": "Version 1",
                "published_at": "2026-05-01T00:00:00Z",
                "prerelease": False,
                "draft": False,
                "html_url": "https://github.com/owner/repo/releases/tag/v1.0.0",
            }
        ],
    }
    assert "body" not in result["items"][0]
    assert "assets" not in result["items"][0]
    assert "author" not in result["items"][0]
    assert client.calls == [("/repos/owner/repo/releases", {"per_page": 10})]


def test_get_actions_runs_summary_without_permission_returns_unavailable():
    tools, client = make_tools(private_mode=True, permissions={})

    result = tools.get_actions_runs_summary()

    assert result == {"available": False, "missing_permission": "actions:read"}
    assert client.calls == []


def test_get_actions_runs_summary_with_read_permission_calls_actions_endpoint():
    tools, client = make_tools(private_mode=True, permissions={"actions": "read"})

    result = tools.get_actions_runs_summary()

    assert result == {
        "available": True,
        "total_count": 2,
        "conclusion_counts": {"success": 1, "failure": 1},
        "status_counts": {"completed": 2},
        "recent_runs": [
            {
                "id": 1,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "event": "push",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:01:00Z",
                "html_url": "https://github.com/owner/repo/actions/runs/1",
            },
            {
                "id": 2,
                "name": "CI",
                "status": "completed",
                "conclusion": "failure",
                "event": "pull_request",
                "created_at": "2026-05-02T00:00:00Z",
                "updated_at": "2026-05-02T00:01:00Z",
                "html_url": "https://github.com/owner/repo/actions/runs/2",
            },
        ],
    }
    assert client.calls == [("/repos/owner/repo/actions/runs", {"per_page": 20})]


def test_get_actions_runs_summary_returns_bounded_summary_and_drops_nested_fields():
    tools, client = make_tools(
        private_mode=True,
        permissions={"actions": "read"},
        fixtures={
            "/repos/owner/repo/actions/runs": {
                "total_count": 3,
                "workflow_runs": [
                    {
                        "id": 1,
                        "name": "CI",
                        "status": "completed",
                        "conclusion": "success",
                        "event": "push",
                        "created_at": "2026-05-01T00:00:00Z",
                        "updated_at": "2026-05-01T00:01:00Z",
                        "html_url": "https://github.com/owner/repo/actions/runs/1",
                        "actor": {"login": "octocat"},
                        "head_commit": {"message": "secret context"},
                        "repository": {"full_name": "owner/repo"},
                    },
                    {
                        "id": 2,
                        "name": "CI",
                        "status": "completed",
                        "conclusion": "failure",
                        "event": "pull_request",
                        "created_at": "2026-05-02T00:00:00Z",
                        "updated_at": "2026-05-02T00:01:00Z",
                        "html_url": "https://github.com/owner/repo/actions/runs/2",
                        "actor": {"login": "octocat"},
                        "head_commit": {"message": "secret context"},
                        "repository": {"full_name": "owner/repo"},
                    },
                    {
                        "id": 3,
                        "name": "Deploy",
                        "status": "in_progress",
                        "conclusion": None,
                        "event": "workflow_dispatch",
                        "created_at": "2026-05-03T00:00:00Z",
                        "updated_at": "2026-05-03T00:01:00Z",
                        "html_url": "https://github.com/owner/repo/actions/runs/3",
                        "actor": {"login": "octocat"},
                        "head_commit": {"message": "secret context"},
                        "repository": {"full_name": "owner/repo"},
                    },
                ],
            }
        },
    )

    result = tools.get_actions_runs_summary()

    assert result == {
        "available": True,
        "total_count": 3,
        "conclusion_counts": {"success": 1, "failure": 1},
        "status_counts": {"completed": 2, "in_progress": 1},
        "recent_runs": [
            {
                "id": 1,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "event": "push",
                "created_at": "2026-05-01T00:00:00Z",
                "updated_at": "2026-05-01T00:01:00Z",
                "html_url": "https://github.com/owner/repo/actions/runs/1",
            },
            {
                "id": 2,
                "name": "CI",
                "status": "completed",
                "conclusion": "failure",
                "event": "pull_request",
                "created_at": "2026-05-02T00:00:00Z",
                "updated_at": "2026-05-02T00:01:00Z",
                "html_url": "https://github.com/owner/repo/actions/runs/2",
            },
            {
                "id": 3,
                "name": "Deploy",
                "status": "in_progress",
                "conclusion": None,
                "event": "workflow_dispatch",
                "created_at": "2026-05-03T00:00:00Z",
                "updated_at": "2026-05-03T00:01:00Z",
                "html_url": "https://github.com/owner/repo/actions/runs/3",
            },
        ],
    }
    for run in result["recent_runs"]:
        assert "actor" not in run
        assert "head_commit" not in run
        assert "repository" not in run
    assert client.calls == [("/repos/owner/repo/actions/runs", {"per_page": 20})]


@pytest.mark.parametrize(
    ("method_name", "fixtures", "expected"),
    [
        (
            "get_repo_summary",
            {"/repos/owner/repo": "not a dict"},
            {
                "full_name": "owner/repo",
                "stars": 0,
                "forks": 0,
                "open_issues": 0,
                "archived": False,
                "fork": False,
                "default_branch": None,
                "license": None,
                "source": "https://github.com/owner/repo",
            },
        ),
        (
            "get_language_breakdown",
            {"/repos/owner/repo/languages": ["not", "a", "dict"]},
            {"total_bytes": 0, "languages": []},
        ),
        (
            "get_releases",
            {"/repos/owner/repo/releases": {"not": "a list"}},
            {"available": False, "error": "malformed_response", "count": 0, "items": []},
        ),
        (
            "get_actions_runs_summary",
            {"/repos/owner/repo/actions/runs": ["not", "a", "dict"]},
            {
                "available": False,
                "error": "malformed_response",
                "total_count": 0,
                "conclusion_counts": {},
                "status_counts": {},
                "recent_runs": [],
            },
        ),
    ],
)
def test_tools_return_controlled_structures_for_malformed_client_responses(method_name, fixtures, expected):
    tools, _client = make_tools(
        private_mode=True,
        permissions={"actions": "read"},
        fixtures=fixtures,
    )

    result = getattr(tools, method_name)()

    assert result == expected


def test_actions_permissions_non_dict_does_not_crash_and_returns_unavailable():
    tools, client = make_tools(private_mode=True, permissions=["not", "a", "dict"])

    result = tools.get_actions_runs_summary()

    assert result == {"available": False, "missing_permission": "actions:read"}
    assert client.calls == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            PermissionRequiredError("GitHub API permission is required."),
            {"available": False, "missing_permission": "actions:read"},
        ),
        (
            NotFoundError("GitHub repository was not found."),
            {"available": False, "reason": "not_found"},
        ),
    ],
)
def test_actions_permission_and_not_found_errors_return_unavailable(error, expected):
    tools, client = make_tools(
        private_mode=True,
        permissions={"actions": "read"},
        errors={"/repos/owner/repo/actions/runs": error},
    )

    result = tools.get_actions_runs_summary()

    assert result == expected
    assert client.calls == [("/repos/owner/repo/actions/runs", {"per_page": 20})]


def test_get_actions_runs_summary_with_write_permission_can_read():
    tools, client = make_tools(private_mode=True, permissions={"actions": "write"})

    result = tools.get_actions_runs_summary()

    assert result["available"] is True
    assert client.calls == [("/repos/owner/repo/actions/runs", {"per_page": 20})]


def test_get_actions_runs_summary_with_admin_permission_can_read():
    tools, client = make_tools(private_mode=True, permissions={"actions": "admin"})

    result = tools.get_actions_runs_summary()

    assert result["available"] is True
    assert client.calls == [("/repos/owner/repo/actions/runs", {"per_page": 20})]
