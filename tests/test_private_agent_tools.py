import pytest
import math

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
        fixtures = {
            "/repos/owner/repo/traffic/views": {
                "count": 10,
                "uniques": 5,
                "views": [{"timestamp": "2026-05-01T00:00:00Z", "count": 3, "uniques": 2}],
            },
            "/repos/owner/repo/traffic/clones": {
                "count": 7,
                "uniques": 4,
                "clones": [{"timestamp": "2026-05-01T00:00:00Z", "count": 2, "uniques": 1}],
            },
            "/repos/owner/repo/traffic/popular/referrers": [
                {
                    "referrer": f"referrer-{index}.example",
                    "count": index + 20,
                    "uniques": index + 10,
                    "extra": "do not leak",
                }
                for index in range(12)
            ],
            "/repos/owner/repo/traffic/popular/paths": [
                {
                    "path": f"/owner/repo/path-{index}",
                    "title": f"Path {index}",
                    "count": index + 30,
                    "uniques": index + 15,
                    "extra": "do not leak",
                }
                for index in range(12)
            ],
            "/repos/owner/repo/dependency-graph/sbom/generate-report": {
                "sbom": {
                    "packages": [
                        {
                            "name": f"package-{index}",
                            "versionInfo": f"1.0.{index}",
                            "licenseConcluded": "MIT",
                            "externalRefs": [{"referenceLocator": "https://example.invalid/private"}],
                        }
                        for index in range(25)
                    ]
                }
            },
            "/repos/owner/repo/dependabot/alerts": [
                {
                    "number": 1,
                    "state": "open",
                    "dependency": {"package": {"name": "flask", "ecosystem": "pip"}},
                    "security_vulnerability": {"severity": "high", "package": {"name": "flask"}},
                    "security_advisory": {"summary": "private advisory details"},
                    "html_url": "https://github.com/owner/repo/security/dependabot/1",
                },
                {
                    "number": 2,
                    "state": "fixed",
                    "dependency": {"package": {"name": "jinja2", "ecosystem": "pip"}},
                    "security_vulnerability": {"severity": "medium", "package": {"name": "jinja2"}},
                    "security_advisory": {"summary": "private advisory details"},
                    "html_url": "https://github.com/owner/repo/security/dependabot/2",
                },
            ],
            "/repos/owner/repo/code-scanning/alerts": [
                {
                    "number": 1,
                    "state": "open",
                    "rule": {"id": "py/sql-injection", "severity": "error", "description": "private code path"},
                    "tool": {"name": "CodeQL"},
                    "most_recent_instance": {"message": {"text": "private code context"}},
                    "html_url": "https://github.com/owner/repo/security/code-scanning/1",
                },
                {
                    "number": 2,
                    "state": "dismissed",
                    "rule": {"id": "py/path-injection", "security_severity_level": "high"},
                    "tool": {"name": "CodeQL"},
                    "most_recent_instance": {"message": {"text": "private code context"}},
                    "html_url": "https://github.com/owner/repo/security/code-scanning/2",
                },
            ],
            "/repos/owner/repo/secret-scanning/alerts": [
                {
                    "number": 1,
                    "state": "open",
                    "secret_type": "github_personal_access_token",
                    "secret": "ghp_private_secret_value",
                    "html_url": "https://github.com/owner/repo/security/secret-scanning/1",
                },
                {
                    "number": 2,
                    "state": "resolved",
                    "secret_type": "slack_webhook_url",
                    "secret": "https://hooks.slack.invalid/private",
                    "html_url": "https://github.com/owner/repo/security/secret-scanning/2",
                },
            ],
        }
        fixtures.update(self.fixtures)
        return fixtures[path]


def make_tools(permissions=None, fixtures=None, errors=None):
    client = FakeClient(fixtures=fixtures, errors=errors)
    tools = GithubAgentTools(
        client,
        RepoRef("owner", "repo"),
        private_mode=True,
        permissions={} if permissions is None else permissions,
    )
    return tools, client


@pytest.mark.parametrize(
    ("method_name", "permission"),
    [
        ("get_traffic_summary", "administration:read"),
        ("get_sbom_summary", "contents:read"),
        ("get_dependabot_alerts_summary", "vulnerability_alerts:read"),
        ("get_code_scanning_alerts_summary", "security_events:read"),
        ("get_secret_scanning_alerts_summary", "secret_scanning_alerts:read"),
    ],
)
def test_private_tools_without_permission_return_unavailable_and_do_not_call_api(method_name, permission):
    tools, client = make_tools(permissions={})

    result = getattr(tools, method_name)()

    assert result == {"available": False, "missing_permission": permission}
    assert client.calls == []


def test_traffic_summary_requires_administration_read_and_drops_daily_lists():
    tools, client = make_tools(permissions={"administration": "read"})

    result = tools.get_traffic_summary()

    assert result == {
        "available": True,
        "views": {"count": 10, "uniques": 5},
        "clones": {"count": 7, "uniques": 4},
        "referrers": [
            {"referrer": f"referrer-{index}.example", "count": index + 20, "uniques": index + 10}
            for index in range(10)
        ],
        "paths": [
            {
                "path": f"/owner/repo/path-{index}",
                "title": f"Path {index}",
                "count": index + 30,
                "uniques": index + 15,
            }
            for index in range(10)
        ],
    }
    assert "views" not in result["views"]
    assert "clones" not in result["clones"]
    assert "extra" not in result["referrers"][0]
    assert "extra" not in result["paths"][0]
    assert client.calls == [
        ("/repos/owner/repo/traffic/views", None),
        ("/repos/owner/repo/traffic/clones", None),
        ("/repos/owner/repo/traffic/popular/referrers", None),
        ("/repos/owner/repo/traffic/popular/paths", None),
    ]


def test_sbom_summary_requires_contents_read_and_trims_packages():
    tools, client = make_tools(permissions={"contents": "read"})

    result = tools.get_sbom_summary()

    assert result["available"] is True
    assert result["package_count"] == 25
    assert result["packages"] == [
        {"name": f"package-{index}", "version": f"1.0.{index}"}
        for index in range(20)
    ]
    assert "sbom" not in result
    assert client.calls == [("/repos/owner/repo/dependency-graph/sbom/generate-report", None)]


def test_sbom_summary_fetches_same_origin_generated_report_and_hides_report_url():
    tools, client = make_tools(
        permissions={"contents": "read"},
        fixtures={
            "/repos/owner/repo/dependency-graph/sbom/generate-report": {
                "sbom_url": "https://api.github.com/repos/owner/repo/dependency-graph/sbom/fetch-report/report-id"
            },
            "/repos/owner/repo/dependency-graph/sbom/fetch-report/report-id": {
                "sbom": {
                    "packages": [
                        {"name": "flask", "versionInfo": "3.0.0", "supplier": "private supplier"},
                    ]
                }
            },
        },
    )

    result = tools.get_sbom_summary()

    assert result == {
        "available": True,
        "package_count": 1,
        "packages": [{"name": "flask", "version": "3.0.0"}],
    }
    assert "sbom_url" not in result
    assert "sbom" not in result
    assert client.calls == [
        ("/repos/owner/repo/dependency-graph/sbom/generate-report", None),
        ("/repos/owner/repo/dependency-graph/sbom/fetch-report/report-id", None, {"allow_redirects": False}),
    ]


def test_sbom_summary_does_not_leak_unparsed_generated_report_url_or_full_sbom():
    tools, client = make_tools(
        permissions={"contents": "read"},
        fixtures={
            "/repos/owner/repo/dependency-graph/sbom/generate-report": {
                "sbom_url": "https://api.github.com/repos/other/repo/dependency-graph/sbom/fetch-report/report-id",
                "private": "do not leak",
            }
        },
    )

    result = tools.get_sbom_summary()

    assert result == {
        "available": True,
        "status": "report_requested",
        "package_count": 0,
        "packages": [],
    }
    assert "sbom_url" not in result
    assert "sbom" not in result
    assert client.calls == [("/repos/owner/repo/dependency-graph/sbom/generate-report", None)]


def test_sbom_summary_returns_processing_for_fetch_report_202_payload():
    tools, client = make_tools(
        permissions={"contents": "read"},
        fixtures={
            "/repos/owner/repo/dependency-graph/sbom/generate-report": {
                "sbom_url": "https://api.github.com/repos/owner/repo/dependency-graph/sbom/fetch-report/report-id"
            },
            "/repos/owner/repo/dependency-graph/sbom/fetch-report/report-id": {"status_code": 202},
        },
    )

    result = tools.get_sbom_summary()

    assert result == {
        "available": True,
        "status": "processing",
        "package_count": 0,
        "packages": [],
    }
    assert client.calls == [
        ("/repos/owner/repo/dependency-graph/sbom/generate-report", None),
        ("/repos/owner/repo/dependency-graph/sbom/fetch-report/report-id", None, {"allow_redirects": False}),
    ]


def test_sbom_summary_returns_report_ready_without_following_temporary_redirect_url():
    tools, client = make_tools(
        permissions={"contents": "read"},
        fixtures={
            "/repos/owner/repo/dependency-graph/sbom/generate-report": {
                "sbom_url": "https://api.github.com/repos/owner/repo/dependency-graph/sbom/fetch-report/report-id"
            },
            "/repos/owner/repo/dependency-graph/sbom/fetch-report/report-id": {
                "status_code": 302,
                "location": "https://private-download.example/sbom.json",
            },
        },
    )

    result = tools.get_sbom_summary()

    assert result == {
        "available": True,
        "status": "report_ready",
        "package_count": 0,
        "packages": [],
    }
    assert "location" not in result
    assert client.calls == [
        ("/repos/owner/repo/dependency-graph/sbom/generate-report", None),
        ("/repos/owner/repo/dependency-graph/sbom/fetch-report/report-id", None, {"allow_redirects": False}),
    ]


def test_dependabot_alerts_summary_counts_and_trims_alert_fields():
    alerts = [
        {
            "number": index,
            "state": "open" if index % 2 else "fixed",
            "dependency": {"package": {"name": f"package-{index}", "ecosystem": "pip"}},
            "security_vulnerability": {
                "severity": "critical" if index % 3 == 0 else "high",
                "package": {"name": f"package-{index}"},
            },
            "security_advisory": {"summary": "do not leak advisory text"},
            "html_url": f"https://github.com/owner/repo/security/dependabot/{index}",
        }
        for index in range(12)
    ]
    tools, client = make_tools(
        permissions={"vulnerability_alerts": "read"},
        fixtures={"/repos/owner/repo/dependabot/alerts": alerts},
    )

    result = tools.get_dependabot_alerts_summary()

    assert result["available"] is True
    assert result["open_alerts"] == 6
    assert result["severity_counts"] == {"high": 8, "critical": 4}
    assert result["state_counts"] == {"fixed": 6, "open": 6}
    assert len(result["alerts"]) == 10
    assert result["alerts"][0] == {
        "number": 0,
        "state": "fixed",
        "severity": "critical",
        "package": "package-0",
        "ecosystem": "pip",
        "html_url": "https://github.com/owner/repo/security/dependabot/0",
    }
    assert "security_advisory" not in result["alerts"][0]
    assert client.calls == [("/repos/owner/repo/dependabot/alerts", {"per_page": 100})]


def test_code_scanning_alerts_summary_counts_and_trims_alert_fields():
    alerts = [
        {
            "number": index,
            "state": "open" if index < 3 else "dismissed",
            "rule": {
                "id": "py/sql-injection" if index % 2 else "py/path-injection",
                "severity": "error" if index % 2 else None,
                "security_severity_level": "high" if index % 2 == 0 else None,
                "description": "do not leak code context",
            },
            "tool": {"name": "CodeQL"},
            "most_recent_instance": {"message": {"text": "private code context"}},
            "html_url": f"https://github.com/owner/repo/security/code-scanning/{index}",
        }
        for index in range(11)
    ]
    tools, client = make_tools(
        permissions={"security_events": "read"},
        fixtures={"/repos/owner/repo/code-scanning/alerts": alerts},
    )

    result = tools.get_code_scanning_alerts_summary()

    assert result["available"] is True
    assert result["open_alerts"] == 3
    assert result["severity_counts"] == {"high": 6, "error": 5}
    assert result["rule_counts"] == {"py/path-injection": 6, "py/sql-injection": 5}
    assert result["state_counts"] == {"open": 3, "dismissed": 8}
    assert len(result["alerts"]) == 10
    assert result["alerts"][0] == {
        "number": 0,
        "state": "open",
        "rule_id": "py/path-injection",
        "severity": "high",
        "tool": "CodeQL",
        "html_url": "https://github.com/owner/repo/security/code-scanning/0",
    }
    assert "most_recent_instance" not in result["alerts"][0]
    assert client.calls == [("/repos/owner/repo/code-scanning/alerts", {"per_page": 100})]


def test_code_scanning_state_counts_uses_all_returned_alerts_not_trimmed_alerts():
    alerts = [
        {
            "number": index,
            "state": "open" if index < 10 else "dismissed",
            "rule": {"id": "py/sql-injection", "severity": "error"},
            "tool": {"name": "CodeQL"},
            "html_url": f"https://github.com/owner/repo/security/code-scanning/{index}",
        }
        for index in range(15)
    ]
    tools, _client = make_tools(
        permissions={"security_events": "read"},
        fixtures={"/repos/owner/repo/code-scanning/alerts": alerts},
    )

    result = tools.get_code_scanning_alerts_summary()

    assert len(result["alerts"]) == 10
    assert result["state_counts"] == {"open": 10, "dismissed": 5}


def test_secret_scanning_alerts_summary_counts_and_trims_alert_fields():
    alerts = [
        {
            "number": index,
            "state": "open" if index < 4 else "resolved",
            "secret_type": "github_personal_access_token" if index % 2 else "slack_webhook_url",
            "secret": "do_not_leak_secret_value",
            "html_url": f"https://github.com/owner/repo/security/secret-scanning/{index}",
        }
        for index in range(13)
    ]
    tools, client = make_tools(
        permissions={"secret_scanning_alerts": "read"},
        fixtures={"/repos/owner/repo/secret-scanning/alerts": alerts},
    )

    result = tools.get_secret_scanning_alerts_summary()

    assert result["available"] is True
    assert result["open_alerts"] == 4
    assert result["state_counts"] == {"open": 4, "resolved": 9}
    assert result["secret_type_counts"] == {"slack_webhook_url": 7, "github_personal_access_token": 6}
    assert len(result["alerts"]) == 10
    assert result["alerts"][0] == {
        "number": 0,
        "state": "open",
        "secret_type": "slack_webhook_url",
        "html_url": "https://github.com/owner/repo/security/secret-scanning/0",
    }
    assert "secret" not in result["alerts"][0]
    assert client.calls == [("/repos/owner/repo/secret-scanning/alerts", {"per_page": 100})]


def test_traffic_permission_error_returns_unavailable():
    tools, client = make_tools(
        permissions={"administration": "read"},
        errors={"/repos/owner/repo/traffic/views": PermissionRequiredError("missing administration read")},
    )

    result = tools.get_traffic_summary()

    assert result == {"available": False, "missing_permission": "administration:read"}
    assert client.calls == [("/repos/owner/repo/traffic/views", None)]


def test_sbom_not_found_returns_not_found():
    tools, client = make_tools(
        permissions={"contents": "read"},
        errors={"/repos/owner/repo/dependency-graph/sbom/generate-report": NotFoundError("missing sbom")},
    )

    result = tools.get_sbom_summary()

    assert result == {"available": False, "reason": "not_found"}
    assert client.calls == [("/repos/owner/repo/dependency-graph/sbom/generate-report", None)]


def test_traffic_malformed_popular_response_returns_controlled_error():
    tools, client = make_tools(
        permissions={"administration": "read"},
        fixtures={"/repos/owner/repo/traffic/popular/referrers": {"not": "a list"}},
    )

    result = tools.get_traffic_summary()

    assert result == {
        "available": False,
        "error": "malformed_response",
        "views": {"count": 0, "uniques": 0},
        "clones": {"count": 0, "uniques": 0},
        "referrers": [],
        "paths": [],
    }
    assert client.calls == [
        ("/repos/owner/repo/traffic/views", None),
        ("/repos/owner/repo/traffic/clones", None),
        ("/repos/owner/repo/traffic/popular/referrers", None),
        ("/repos/owner/repo/traffic/popular/paths", None),
    ]


def test_dependabot_malformed_response_returns_controlled_error():
    tools, client = make_tools(
        permissions={"vulnerability_alerts": "read"},
        fixtures={"/repos/owner/repo/dependabot/alerts": {"not": "a list"}},
    )

    result = tools.get_dependabot_alerts_summary()

    assert result == {
        "available": False,
        "error": "malformed_response",
        "open_alerts": 0,
        "severity_counts": {},
        "state_counts": {},
        "alerts": [],
    }
    assert client.calls == [("/repos/owner/repo/dependabot/alerts", {"per_page": 100})]


def test_safe_int_returns_zero_for_nan_and_infinity():
    assert GithubAgentTools._safe_int(math.nan) == 0
    assert GithubAgentTools._safe_int(math.inf) == 0
    assert GithubAgentTools._safe_int(-math.inf) == 0
