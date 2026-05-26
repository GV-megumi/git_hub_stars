from datetime import datetime, timezone

import pytest

from app.errors import GithubApiError, ValidationError
from app.github.url_parser import RepoRef


FIXED_NOW = datetime(2026, 5, 26, 12, 0, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, overrides=None, failures=None, failure_exceptions=None):
        self.overrides = overrides or {}
        self.failures = set(failures or [])
        self.failure_exceptions = failure_exceptions or {}
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append((path, params))
        if path in self.failure_exceptions:
            raise self.failure_exceptions[path]
        if path in self.failures:
            raise GithubApiError("GitHub API request failed.")

        fixtures = {
            "/repos/owner/repo": {
                "full_name": "owner/repo",
                "description": "Example",
                "stargazers_count": 10,
                "forks_count": 2,
                "subscribers_count": 3,
                "watchers_count": 8,
                "open_issues_count": 4,
                "default_branch": "main",
                "license": {"spdx_id": "MIT"},
                "archived": False,
                "disabled": False,
                "fork": False,
                "pushed_at": "2026-05-20T00:00:00Z",
                "updated_at": "2026-05-21T00:00:00Z",
                "created_at": "2025-01-01T00:00:00Z",
                "size": 123,
            },
            "/repos/owner/repo/languages": {"Python": 900, "HTML": 100},
            "/repos/owner/repo/community/profile": {
                "health_percentage": 80,
                "files": {
                    "readme": {"url": "x"},
                    "license": {"url": "y"},
                    "contributing": None,
                    "code_of_conduct": {},
                },
            },
            "/repos/owner/repo/releases": [
                {"tag_name": "v1.0.0", "published_at": "2026-05-01T00:00:00Z"}
            ],
            "/repos/owner/repo/contributors": [{"login": "alice"}, {"login": "bob"}],
            "/repos/owner/repo/commits": [
                {"sha": "1", "commit": {"author": {"date": "2026-05-20T00:00:00Z"}}},
                {"sha": "2", "commit": {"author": {"date": "2026-04-20T00:00:00Z"}}},
            ],
            "/repos/owner/repo/pulls": [{"number": 5}],
        }
        fixtures.update(self.overrides)
        return fixtures[path]


def test_collect_repository_snapshot_normalizes_core_fields():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient()
    snapshot = collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert snapshot.repo.full_name == "owner/repo"
    assert snapshot.repo.description == "Example"
    assert snapshot.repo.stars == 10
    assert snapshot.repo.forks == 2
    assert snapshot.repo.watchers == 3
    assert snapshot.repo.open_issues == 4
    assert snapshot.repo.default_branch == "main"
    assert snapshot.repo.license_spdx == "MIT"
    assert snapshot.repo.archived is False
    assert snapshot.repo.disabled is False
    assert snapshot.repo.fork is False
    assert snapshot.repo.pushed_at == "2026-05-20T00:00:00Z"
    assert snapshot.repo.updated_at == "2026-05-21T00:00:00Z"
    assert snapshot.repo.created_at == "2025-01-01T00:00:00Z"
    assert snapshot.repo.size_kb == 123
    assert snapshot.languages == {"Python": 90.0, "HTML": 10.0}
    assert snapshot.community.health_percentage == 80
    assert snapshot.community.files == {
        "readme": True,
        "license": True,
        "contributing": False,
        "code_of_conduct": False,
    }
    assert snapshot.activity.recent_commits_count == 2
    assert snapshot.activity.commits_90d_count == 2
    assert snapshot.activity.commits_30d_count == 1
    assert snapshot.activity.contributors_count == 2
    assert snapshot.activity.releases_count == 1
    assert snapshot.activity.releases_count_is_sampled is True
    assert snapshot.activity.latest_release_at == "2026-05-01T00:00:00Z"
    assert snapshot.activity.open_pulls_count == 1
    assert snapshot.partial_errors == []


def test_collect_repository_snapshot_uses_required_endpoints_and_params():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient()
    collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert client.calls == [
        ("/repos/owner/repo", None),
        ("/repos/owner/repo/languages", None),
        ("/repos/owner/repo/community/profile", None),
        ("/repos/owner/repo/releases", {"per_page": 10}),
        ("/repos/owner/repo/contributors", {"per_page": 100}),
        ("/repos/owner/repo/commits", {"per_page": 100, "since": "2026-02-25T12:00:00Z"}),
        ("/repos/owner/repo/pulls", {"state": "open", "per_page": 100}),
    ]


def test_commit_activity_counts_are_time_scoped_from_90_day_sample():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient(
        overrides={
            "/repos/owner/repo/commits": [
                {"sha": "1", "commit": {"author": {"date": "2026-05-25T12:00:00Z"}}},
                {"sha": "2", "commit": {"author": {"date": "2026-04-26T12:00:00Z"}}},
                {"sha": "3", "commit": {"author": {"date": "2026-04-26T11:59:59Z"}}},
                {
                    "sha": "4",
                    "commit": {
                        "author": {"date": None},
                        "committer": {"date": "2026-05-01T00:00:00Z"},
                    },
                },
            ]
        }
    )

    snapshot = collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert snapshot.activity.commits_90d_count == 4
    assert snapshot.activity.recent_commits_count == 4
    assert snapshot.activity.commits_30d_count == 3


def test_commit_activity_prefers_committer_date_for_recent_maintenance():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient(
        overrides={
            "/repos/owner/repo/commits": [
                {
                    "sha": "merge",
                    "commit": {
                        "author": {"date": "2026-01-01T00:00:00Z"},
                        "committer": {"date": "2026-05-20T00:00:00Z"},
                    },
                }
            ]
        }
    )

    snapshot = collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert snapshot.activity.commits_30d_count == 1


def test_commit_activity_falls_back_to_author_date_when_committer_date_is_invalid():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient(
        overrides={
            "/repos/owner/repo/commits": [
                {
                    "sha": "fallback-author",
                    "commit": {
                        "author": {"date": "2026-05-20T00:00:00Z"},
                        "committer": {"date": "not-a-date"},
                    },
                }
            ]
        }
    )

    snapshot = collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert snapshot.activity.commits_30d_count == 1
    assert snapshot.activity.commits_90d_count == 1
    assert snapshot.activity.recent_commits_count == 1


def test_commit_90d_count_uses_parsed_dates_not_raw_sample_length():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient(
        overrides={
            "/repos/owner/repo/commits": [
                {
                    "sha": "within-90d",
                    "commit": {"committer": {"date": "2026-05-01T00:00:00Z"}},
                },
                {
                    "sha": "outside-90d",
                    "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}},
                },
                {
                    "sha": "bad-date",
                    "commit": {"committer": {"date": "not-a-date"}},
                },
            ]
        }
    )

    snapshot = collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert snapshot.activity.commits_90d_count == 1
    assert snapshot.activity.recent_commits_count == 1


def test_latest_release_uses_max_published_at_instead_of_list_order():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient(
        overrides={
            "/repos/owner/repo/releases": [
                {"tag_name": "v1.0.0", "published_at": "2026-03-01T00:00:00Z"},
                {"tag_name": "v2.0.0", "published_at": "2026-05-01T00:00:00Z"},
                {"tag_name": "v1.5.0", "created_at": "2026-04-01T00:00:00Z"},
            ]
        }
    )

    snapshot = collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert snapshot.activity.latest_release_at == "2026-05-01T00:00:00Z"


def test_auxiliary_endpoint_failures_fall_back_to_defaults():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient(
        failures=[
            "/repos/owner/repo/community/profile",
            "/repos/owner/repo/releases",
            "/repos/owner/repo/contributors",
            "/repos/owner/repo/commits",
            "/repos/owner/repo/pulls",
        ]
    )

    snapshot = collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert snapshot.community.health_percentage is None
    assert snapshot.community.files == {}
    assert snapshot.activity.recent_commits_count == 0
    assert snapshot.activity.commits_90d_count == 0
    assert snapshot.activity.commits_30d_count == 0
    assert snapshot.activity.contributors_count == 0
    assert snapshot.activity.releases_count == 0
    assert snapshot.activity.latest_release_at is None
    assert snapshot.activity.open_pulls_count == 0
    assert [
        {
            "path": error["path"],
            "code": error["code"],
            "message": error["message"],
        }
        for error in snapshot.partial_errors
    ] == [
        {
            "path": "/repos/owner/repo/community/profile",
            "code": "github_api_error",
            "message": "GitHub API request failed.",
        },
        {
            "path": "/repos/owner/repo/releases",
            "code": "github_api_error",
            "message": "GitHub API request failed.",
        },
        {
            "path": "/repos/owner/repo/contributors",
            "code": "github_api_error",
            "message": "GitHub API request failed.",
        },
        {
            "path": "/repos/owner/repo/commits",
            "code": "github_api_error",
            "message": "GitHub API request failed.",
        },
        {
            "path": "/repos/owner/repo/pulls",
            "code": "github_api_error",
            "message": "GitHub API request failed.",
        },
    ]


def test_auxiliary_failure_partial_error_preserves_github_context():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient(
        failure_exceptions={
            "/repos/owner/repo/releases": GithubApiError(
                "GitHub API request failed: upstream unavailable.",
                github_status_code=502,
                github_path="/repos/owner/repo/releases",
                github_message="Bad Gateway",
            )
        }
    )

    snapshot = collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert snapshot.partial_errors == [
        {
            "path": "/repos/owner/repo/releases",
            "error": "github_api_error",
            "code": "github_api_error",
            "message": "GitHub API request failed: upstream unavailable.",
            "github_status_code": 502,
            "github_path": "/repos/owner/repo/releases",
            "github_message": "Bad Gateway",
        }
    ]


def test_validation_error_from_auxiliary_endpoint_is_not_swallowed():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient(
        failure_exceptions={
            "/repos/owner/repo/community/profile": ValidationError("Invalid internal GitHub API path.")
        }
    )

    with pytest.raises(ValidationError):
        collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)


def test_language_percentages_return_empty_when_total_bytes_is_zero():
    from app.analyzer.collector import collect_repository_snapshot

    client = FakeClient(overrides={"/repos/owner/repo/languages": {"Python": 0, "HTML": 0}})

    snapshot = collect_repository_snapshot(client, RepoRef("owner", "repo"), now=FIXED_NOW)

    assert snapshot.languages == {}


def test_main_repo_and_languages_errors_are_not_suppressed():
    from app.analyzer.collector import collect_repository_snapshot

    with pytest.raises(GithubApiError):
        collect_repository_snapshot(
            FakeClient(failures=["/repos/owner/repo"]),
            RepoRef("owner", "repo"),
        )

    with pytest.raises(GithubApiError):
        collect_repository_snapshot(
            FakeClient(failures=["/repos/owner/repo/languages"]),
            RepoRef("owner", "repo"),
        )
