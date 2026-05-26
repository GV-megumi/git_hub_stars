import base64

import pytest

from app.agent.tools import GithubAgentTools
from app.errors import NotFoundError, PermissionRequiredError
from app.github.url_parser import RepoRef


class FakeClient:
    def __init__(self, fixtures=None, errors=None):
        self.calls = []
        self.fixtures = fixtures or {}
        self.errors = errors or {}

    def get_json(self, path, params=None, **kwargs):
        call = (path, params)
        if kwargs:
            call = (path, params, kwargs)
        self.calls.append(call)
        if path in self.errors:
            raise self.errors[path]
        readme_text = "# Repo\nPublic documentation"
        contributing_text = "Contributing guide"
        conduct_text = "Code of conduct"
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
            "/repos/owner/repo/community/profile": {
                "health_percentage": 86,
                "files": {
                    "readme": {"name": "README.md"},
                    "license": {"name": "LICENSE"},
                    "contributing": None,
                    "code_of_conduct": {"name": "CODE_OF_CONDUCT.md"},
                    "issue_template": None,
                    "pull_request_template": None,
                    "security": {"name": "SECURITY.md"},
                },
            },
            "/repos/owner/repo/commits": [
                {
                    "sha": "abc123456789",
                    "author": {"login": "alice", "private": "drop"},
                    "commit": {
                        "message": "Add feature\n\nLong body should be dropped",
                        "author": {"name": "Alice", "date": "2026-05-20T00:00:00Z"},
                    },
                    "parents": [{"sha": "parent"}],
                    "files": [{"filename": "secret.py"}],
                    "html_url": "https://github.com/owner/repo/commit/abc123456789",
                },
                {
                    "sha": "def567890000",
                    "author": None,
                    "commit": {
                        "message": "Fix bug",
                        "author": {"name": "Bob", "date": "2026-05-21T00:00:00Z"},
                    },
                    "html_url": "https://github.com/owner/repo/commit/def567890000",
                },
            ],
            "/repos/owner/repo/issues": [
                {
                    "number": 11,
                    "title": "Bug report",
                    "state": "open",
                    "created_at": "2026-05-18T00:00:00Z",
                    "updated_at": "2026-05-19T00:00:00Z",
                    "labels": [{"name": "bug"}, {"name": "triage"}],
                    "body": "drop issue body",
                    "html_url": "https://github.com/owner/repo/issues/11",
                },
                {
                    "number": 12,
                    "title": "Pull request returned by issues endpoint",
                    "pull_request": {"url": "https://api.github.com/repos/owner/repo/pulls/12"},
                },
            ],
            "/repos/owner/repo/pulls": [
                {
                    "number": 7,
                    "title": "Improve tests",
                    "state": "open",
                    "draft": True,
                    "created_at": "2026-05-17T00:00:00Z",
                    "updated_at": "2026-05-18T00:00:00Z",
                    "body": "drop PR body",
                    "html_url": "https://github.com/owner/repo/pull/7",
                }
            ],
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
            "/repos/owner/repo/readme": {
                "name": "README.md",
                "path": "README.md",
                "size": len(readme_text),
                "encoding": "base64",
                "content": base64.b64encode(readme_text.encode()).decode(),
                "html_url": "https://github.com/owner/repo/blob/main/README.md",
                "download_url": "https://raw.githubusercontent.com/owner/repo/main/README.md",
            },
            "/repos/owner/repo/contents/CONTRIBUTING.md": {
                "name": "CONTRIBUTING.md",
                "path": "CONTRIBUTING.md",
                "size": len(contributing_text),
                "encoding": "base64",
                "content": base64.b64encode(contributing_text.encode()).decode(),
                "html_url": "https://github.com/owner/repo/blob/main/CONTRIBUTING.md",
            },
            "/repos/owner/repo/contents/SECURITY.md": {
                "name": "SECURITY.md",
                "path": "SECURITY.md",
                "size": 0,
                "encoding": "base64",
                "content": "",
                "html_url": "https://github.com/owner/repo/blob/main/SECURITY.md",
            },
            "/repos/owner/repo/contents/CODE_OF_CONDUCT.md": {
                "name": "CODE_OF_CONDUCT.md",
                "path": "CODE_OF_CONDUCT.md",
                "size": len(conduct_text),
                "encoding": "base64",
                "content": base64.b64encode(conduct_text.encode()).decode(),
                "html_url": "https://github.com/owner/repo/blob/main/CODE_OF_CONDUCT.md",
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


def test_get_community_profile_returns_expected_file_booleans():
    tools, client = make_tools()

    result = tools.get_community_profile()

    assert result == {
        "available": True,
        "health_percentage": 86,
        "files": {
            "readme": True,
            "license": True,
            "contributing": False,
            "code_of_conduct": True,
            "issue_template": False,
            "pull_request_template": False,
            "security": True,
        },
    }
    assert client.calls == [("/repos/owner/repo/community/profile", None)]


def test_get_recent_commits_returns_bounded_commit_summaries():
    tools, client = make_tools()

    result = tools.get_recent_commits()

    assert result == {
        "available": True,
        "count": 2,
        "items": [
            {
                "sha": "abc1234",
                "author": "alice",
                "message": "Add feature",
                "committed_at": "2026-05-20T00:00:00Z",
                "html_url": "https://github.com/owner/repo/commit/abc123456789",
            },
            {
                "sha": "def5678",
                "author": "Bob",
                "message": "Fix bug",
                "committed_at": "2026-05-21T00:00:00Z",
                "html_url": "https://github.com/owner/repo/commit/def567890000",
            },
        ],
    }
    assert "parents" not in result["items"][0]
    assert "files" not in result["items"][0]
    assert client.calls == [("/repos/owner/repo/commits", {"per_page": 30})]


def test_get_issues_summary_filters_pull_requests_and_drops_bodies():
    tools, client = make_tools()

    result = tools.get_issues_summary()

    assert result == {
        "available": True,
        "open_count": 1,
        "label_counts": {"bug": 1, "triage": 1},
        "recent_issues": [
            {
                "number": 11,
                "title": "Bug report",
                "state": "open",
                "created_at": "2026-05-18T00:00:00Z",
                "updated_at": "2026-05-19T00:00:00Z",
                "labels": ["bug", "triage"],
                "html_url": "https://github.com/owner/repo/issues/11",
            }
        ],
    }
    assert "body" not in result["recent_issues"][0]
    assert client.calls == [("/repos/owner/repo/issues", {"state": "open", "per_page": 30})]


def test_get_pulls_summary_returns_bounded_pull_request_summaries():
    tools, client = make_tools()

    result = tools.get_pulls_summary()

    assert result == {
        "available": True,
        "open_count": 1,
        "draft_count": 1,
        "recent_pulls": [
            {
                "number": 7,
                "title": "Improve tests",
                "state": "open",
                "draft": True,
                "created_at": "2026-05-17T00:00:00Z",
                "updated_at": "2026-05-18T00:00:00Z",
                "html_url": "https://github.com/owner/repo/pull/7",
            }
        ],
    }
    assert "body" not in result["recent_pulls"][0]
    assert client.calls == [("/repos/owner/repo/pulls", {"state": "open", "per_page": 30})]


def test_get_readme_and_key_files_returns_whitelisted_text_excerpts_only():
    tools, client = make_tools(
        errors={"/repos/owner/repo/contents/SECURITY.md": NotFoundError("missing security policy")}
    )

    result = tools.get_readme_and_key_files()

    assert result == {
        "available": True,
        "files": [
            {
                "key": "readme",
                "available": True,
                "name": "README.md",
                "path": "README.md",
                "size": 27,
                "html_url": "https://github.com/owner/repo/blob/main/README.md",
                "text_excerpt": "# Repo\nPublic documentation",
                "text_truncated": False,
            },
            {
                "key": "contributing",
                "available": True,
                "name": "CONTRIBUTING.md",
                "path": "CONTRIBUTING.md",
                "size": 18,
                "html_url": "https://github.com/owner/repo/blob/main/CONTRIBUTING.md",
                "text_excerpt": "Contributing guide",
                "text_truncated": False,
            },
            {
                "key": "security",
                "available": False,
                "reason": "not_found",
                "path": "SECURITY.md",
            },
            {
                "key": "code_of_conduct",
                "available": True,
                "name": "CODE_OF_CONDUCT.md",
                "path": "CODE_OF_CONDUCT.md",
                "size": 15,
                "html_url": "https://github.com/owner/repo/blob/main/CODE_OF_CONDUCT.md",
                "text_excerpt": "Code of conduct",
                "text_truncated": False,
            },
        ],
    }
    assert "download_url" not in result["files"][0]
    assert client.calls == [
        ("/repos/owner/repo/readme", None),
        ("/repos/owner/repo/contents/CONTRIBUTING.md", None),
        ("/repos/owner/repo/contents/SECURITY.md", None),
        ("/repos/owner/repo/contents/CODE_OF_CONDUCT.md", None),
    ]


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
            "get_community_profile",
            {"/repos/owner/repo/community/profile": ["not", "a dict"]},
            {"available": False, "error": "malformed_response", "health_percentage": None, "files": {}},
        ),
        (
            "get_recent_commits",
            {"/repos/owner/repo/commits": {"not": "a list"}},
            {"available": False, "error": "malformed_response", "count": 0, "items": []},
        ),
        (
            "get_issues_summary",
            {"/repos/owner/repo/issues": {"not": "a list"}},
            {"available": False, "error": "malformed_response", "open_count": 0, "label_counts": {}, "recent_issues": []},
        ),
        (
            "get_pulls_summary",
            {"/repos/owner/repo/pulls": {"not": "a list"}},
            {"available": False, "error": "malformed_response", "open_count": 0, "draft_count": 0, "recent_pulls": []},
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
        permissions={"actions": "read", "contents": "read", "issues": "read", "pull_requests": "read"},
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
