from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, BadRequestError

from app.agent.llm import LlmClient
from app.agent.service import build_agent_prompt, run_agent_analysis, should_enable_tavily
from app.agent.tavily import TavilyClient
from app.github.url_parser import RepoRef


def test_tavily_enabled_only_for_public_repo_with_key():
    assert should_enable_tavily(private_mode=False, tavily_api_key="key") is True
    assert should_enable_tavily(private_mode=True, tavily_api_key="key") is False
    assert should_enable_tavily(private_mode=False, tavily_api_key=None) is False
    assert should_enable_tavily(private_mode=False, tavily_api_key="  ") is False


def test_prompt_includes_repo_score_context_and_private_tavily_constraint():
    prompt = build_agent_prompt(
        repo_url="https://github.com/owner/repo",
        system_score={"score": 80, "status": "良好"},
        private_mode=True,
        detected_info={"languages": {"Python": 90.0}},
        github_context={"repo_summary": {"full_name": "owner/repo"}},
        tavily_context={"search_results": [{"url": "https://example.test"}]},
    )

    assert "https://github.com/owner/repo" in prompt
    assert "80" in prompt
    assert "Python" in prompt
    assert "owner/repo" in prompt
    assert "不使用 Tavily" in prompt
    assert "不向公开网页工具发送私有数据" in prompt
    assert "ai_score" in prompt
    assert "references" in prompt
    assert "confidence 只能是 high、medium、low" in prompt
    assert "findings 每项必须包含 level、title、message" in prompt
    assert "references 每项必须包含 title、url、evidence" in prompt
    assert "证据充分时不要机械降为 low" in prompt


def test_tavily_search_posts_expected_body_and_returns_bounded_results():
    long_content = "x" * 1300
    session = FakeSession(
        {
            "results": [
                {
                    "title": "Project docs",
                    "url": "https://docs.example.test",
                    "content": long_content,
                    "score": 0.91,
                    "raw_content": "drop this field",
                }
            ]
        }
    )
    client = TavilyClient("tavily-key", session=session)

    result = client.search("repo health", max_results=3)

    assert session.calls == [
        {
            "url": "https://api.tavily.com/search",
            "headers": {
                "Authorization": "Bearer tavily-key",
                "Content-Type": "application/json",
            },
            "json": {
                "query": "repo health",
                "search_depth": "basic",
                "max_results": 3,
            },
            "timeout": 30,
        }
    ]
    assert result == [
        {
            "title": "Project docs",
            "url": "https://docs.example.test",
            "content": "x" * 1200,
            "score": 0.91,
        }
    ]


def test_tavily_extract_posts_expected_body_and_returns_bounded_results():
    urls = [f"https://example.test/{index}" for index in range(25)]
    long_query = "q" * 450
    long_content = "c" * 1300
    long_raw_content = "r" * 1300
    session = FakeSession(
        {
            "results": [
                {
                    "url": urls[0],
                    "title": "Docs",
                    "content": long_content,
                    "raw_content": long_raw_content,
                    "images": ["drop"],
                }
            ],
            "failed_results": [
                {
                    "url": urls[1],
                    "error": "not found",
                    "status": 404,
                    "debug": "drop",
                }
            ],
        }
    )
    client = TavilyClient("tavily-key", session=session)

    result = client.extract(urls, query=long_query)

    assert session.calls == [
        {
            "url": "https://api.tavily.com/extract",
            "headers": {
                "Authorization": "Bearer tavily-key",
                "Content-Type": "application/json",
            },
            "json": {
                "urls": urls[:20],
                "extract_depth": "basic",
                "query": "q" * 400,
                "chunks_per_source": 3,
            },
            "timeout": 30,
        }
    ]
    assert result == {
        "results": [
            {
                "url": urls[0],
                "title": "Docs",
                "content": "c" * 1200,
                "raw_content": "r" * 1200,
            }
        ],
        "failed_results": [
            {
                "url": urls[1],
                "error": "not found",
                "status": 404,
            }
        ],
    }


def test_llm_client_requests_json_object_response(monkeypatch):
    init_calls = []
    create_calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ai_score": 90}'))]
            )

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            init_calls.append({"base_url": base_url, "api_key": api_key})
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )
    response = client.complete_json("analyze this")

    assert init_calls == [{"base_url": "https://model.example.test/v1", "api_key": "model-key"}]
    assert response == '{"ai_score": 90}'
    assert create_calls[0]["model"] == "model-a"
    assert create_calls[0]["response_format"] == {"type": "json_object"}
    assert create_calls[0]["messages"][0]["role"] == "system"
    assert create_calls[0]["messages"][1] == {"role": "user", "content": "analyze this"}


def test_llm_client_retries_without_response_format_for_unsupported_bad_request(monkeypatch):
    create_calls = []
    response = httpx.Response(400, request=httpx.Request("POST", "https://model.example.test/v1/chat"))

    class FakeCompletions:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            if "response_format" in kwargs:
                raise BadRequestError(
                    "Unsupported parameter: response_format",
                    response=response,
                    body={"error": "unsupported"},
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ai_score": 72}'))]
            )

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )

    assert client.complete_json("analyze this") == '{"ai_score": 72}'
    assert len(create_calls) == 2
    assert create_calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in create_calls[1]


def test_llm_client_wraps_provider_error_after_type_error_response_format_retry(monkeypatch):
    from app.errors import LlmProviderError

    create_calls = []
    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://model.example.test/v1/chat/completions"),
    )

    class FakeCompletions:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            if "response_format" in kwargs:
                raise TypeError("unexpected keyword argument 'response_format'")
            raise APIStatusError(
                "Provider failed",
                response=response,
                body={
                    "code": "model_not_found",
                    "message": "No available channel for model model-a",
                    "type": "new_api_error",
                },
            )

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )

    with pytest.raises(LlmProviderError) as error:
        client.complete_json("analyze this")

    assert len(create_calls) == 2
    assert "response_format" not in create_calls[1]
    assert error.value.to_dict()["provider_error_code"] == "model_not_found"


def test_llm_client_wraps_unrelated_bad_request_without_retry(monkeypatch):
    from app.errors import LlmProviderError

    create_calls = []
    response = httpx.Response(400, request=httpx.Request("POST", "https://model.example.test/v1/chat"))

    class FakeCompletions:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            raise BadRequestError("Model quota exceeded", response=response, body={"error": "quota"})

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )

    with pytest.raises(LlmProviderError) as error:
        client.complete_json("analyze this")
    assert len(create_calls) == 1
    assert error.value.to_dict()["provider_status_code"] == 400


def test_llm_client_does_not_wrap_unrelated_type_error(monkeypatch):
    class FakeCompletions:
        def create(self, **kwargs):
            raise TypeError("local sdk mismatch")

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )

    with pytest.raises(TypeError, match="local sdk mismatch"):
        client.complete_json("analyze this")


def test_llm_client_wraps_provider_status_errors(monkeypatch):
    from app.errors import LlmProviderError

    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://model.example.test/v1/chat/completions"),
    )

    class FakeCompletions:
        def create(self, **kwargs):
            raise APIStatusError(
                "Provider failed",
                response=response,
                body={
                    "error": {
                        "code": "model_not_found",
                        "message": "No available channel for model model-a",
                        "type": "new_api_error",
                    }
                },
            )

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )

    with pytest.raises(LlmProviderError) as error:
        client.complete_json("analyze this")

    payload = error.value.to_dict()
    assert error.value.status_code == 502
    assert payload["error"] == "llm_provider_error"
    assert "MODEL_NAME" in payload["message"]
    assert payload["provider_status_code"] == 503
    assert payload["provider_error_code"] == "model_not_found"
    assert payload["provider_error_type"] == "new_api_error"
    assert payload["provider_message"] == "No available channel for model model-a"
    assert "model-key" not in json.dumps(payload)


def test_llm_client_does_not_expose_unsafe_provider_message(monkeypatch):
    from app.errors import LlmProviderError

    response = httpx.Response(
        401,
        request=httpx.Request("POST", "https://model.example.test/v1/chat/completions"),
    )

    class FakeCompletions:
        def create(self, **kwargs):
            raise APIStatusError(
                "Provider failed",
                response=response,
                body={
                    "code": "invalid_api_key",
                    "message": "Authorization failed for Bearer sk-sensitive-token",
                    "type": "auth_error",
                },
            )

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )

    with pytest.raises(LlmProviderError) as error:
        client.complete_json("analyze this")

    payload = error.value.to_dict()
    assert payload["provider_error_code"] == "invalid_api_key"
    assert payload["provider_error_type"] == "auth_error"
    assert "provider_message" not in payload
    assert "sk-sensitive-token" not in json.dumps(payload)


def test_llm_client_redacts_safe_provider_messages(monkeypatch):
    from app.errors import LlmProviderError

    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://model.example.test/v1/chat/completions"),
    )

    class FakeCompletions:
        def create(self, **kwargs):
            raise APIStatusError(
                "Provider failed",
                response=response,
                body={
                    "code": "model_not_found",
                    "message": "No channel for model-a with api_key=sk-sensitive-token",
                    "type": "new_api_error",
                },
            )

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )

    with pytest.raises(LlmProviderError) as error:
        client.complete_json("analyze this")

    payload = error.value.to_dict()
    assert payload["provider_message"] == "No channel for model-a with api_key=[REDACTED]"
    assert "sk-sensitive-token" not in json.dumps(payload)


def test_llm_client_extracts_provider_error_from_response_json(monkeypatch):
    from app.errors import LlmProviderError

    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://model.example.test/v1/chat/completions"),
        json={
            "error": {
                "code": "model_not_found",
                "message": "No available channel for model model-a",
                "type": "new_api_error",
            }
        },
    )

    class FakeCompletions:
        def create(self, **kwargs):
            raise APIStatusError("Provider failed", response=response, body=None)

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )

    with pytest.raises(LlmProviderError) as error:
        client.complete_json("analyze this")

    payload = error.value.to_dict()
    assert payload["provider_error_code"] == "model_not_found"
    assert payload["provider_error_type"] == "new_api_error"
    assert payload["provider_message"] == "No available channel for model model-a"


def test_llm_client_extracts_provider_error_from_direct_body(monkeypatch):
    from app.errors import LlmProviderError

    response = httpx.Response(
        503,
        request=httpx.Request("POST", "https://model.example.test/v1/chat/completions"),
    )

    class FakeCompletions:
        def create(self, **kwargs):
            raise APIStatusError(
                "Provider failed",
                response=response,
                body={
                    "code": "model_not_found",
                    "message": "No available channel for model model-a",
                    "type": "new_api_error",
                },
            )

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("app.agent.llm.OpenAI", FakeOpenAI)

    client = LlmClient(
        base_url="https://model.example.test/v1",
        api_key="model-key",
        model="model-a",
    )

    with pytest.raises(LlmProviderError) as error:
        client.complete_json("analyze this")

    payload = error.value.to_dict()
    assert payload["provider_error_code"] == "model_not_found"
    assert payload["provider_error_type"] == "new_api_error"
    assert payload["provider_message"] == "No available channel for model model-a"


def test_run_agent_analysis_uses_github_tools_tavily_and_parses_llm_json():
    github_client = FakeGithubClient()
    tavily = FakeTavily()
    llm = FakeLlm(
        {
            "ai_score": 88,
            "confidence": "high",
            "summary": "维护状态良好。",
            "findings": [{"level": "info", "title": "Release recent"}],
            "recommendations": ["继续维护发布说明"],
            "references": [{"title": "Docs", "url": "https://docs.example.test"}],
        }
    )
    settings = make_settings(tavily_api_key="tavily-key")

    result = run_agent_analysis(
        repo_url="https://github.com/owner/repo",
        ref=RepoRef("owner", "repo"),
        system_score={"score": 82, "status": "良好"},
        detected_info={"languages": {"Python": 90.0}},
        private_mode=False,
        settings=settings,
        github_client=github_client,
        llm=llm,
        tavily=tavily,
        permissions={"actions": "read"},
    )

    assert result["ai_score"] == 88
    assert result["agent_score"] == 88
    assert result["confidence"] == "high"
    assert result["summary"] == "维护状态良好。"
    assert result["findings"] == [{"level": "info", "title": "Release recent"}]
    assert result["recommendations"] == ["继续维护发布说明"]
    assert result["references"] == [{"title": "Docs", "url": "https://docs.example.test"}]
    assert result["tavily_enabled"] is True
    assert result["attempted_tools"] == [
        "github.get_repo_summary",
        "github.get_language_breakdown",
        "github.get_community_profile",
        "github.get_recent_commits",
        "github.get_issues_summary",
        "github.get_pulls_summary",
        "github.get_releases",
        "github.get_actions_runs_summary",
        "github.get_readme_and_key_files",
        "tavily.search",
        "tavily.extract",
    ]
    assert result["used_tools"] == [
        "github.get_repo_summary",
        "github.get_language_breakdown",
        "github.get_community_profile",
        "github.get_recent_commits",
        "github.get_issues_summary",
        "github.get_pulls_summary",
        "github.get_releases",
        "github.get_actions_runs_summary",
        "github.get_readme_and_key_files",
        "tavily.search",
        "tavily.extract",
    ]
    assert result["tool_errors"] == []
    assert len(tavily.queries[0]["query"]) <= 400
    assert tavily.queries[0]["max_results"] == 5
    assert tavily.extract_calls == [
        {
            "urls": ["https://docs.example.test"],
            "query": tavily.queries[0]["query"],
        }
    ]
    assert "Tavily" in llm.prompts[0]
    assert "https://docs.example.test" in llm.prompts[0]
    assert "Extracted docs" in llm.prompts[0]
    assert github_client.calls == [
        ("/repos/owner/repo", None),
        ("/repos/owner/repo/languages", None),
        ("/repos/owner/repo/community/profile", None),
        ("/repos/owner/repo/commits", {"per_page": 30}),
        ("/repos/owner/repo/issues", {"state": "open", "per_page": 30}),
        ("/repos/owner/repo/pulls", {"state": "open", "per_page": 30}),
        ("/repos/owner/repo/releases", {"per_page": 10}),
        ("/repos/owner/repo/actions/runs", {"per_page": 20}),
        ("/repos/owner/repo/readme", None),
        ("/repos/owner/repo/contents/CONTRIBUTING.md", None),
        ("/repos/owner/repo/contents/SECURITY.md", None),
        ("/repos/owner/repo/contents/CODE_OF_CONDUCT.md", None),
    ]


def test_run_agent_analysis_private_mode_skips_tavily_even_with_key():
    tavily = ExplodingTavily()
    llm = FakeLlm(
        {
            "ai_score": 61,
            "confidence": "medium",
            "summary": "私有仓库分析。",
            "findings": [],
            "recommendations": [],
            "references": [],
        }
    )

    result = run_agent_analysis(
        repo_url="https://github.com/owner/private-repo",
        ref=RepoRef("owner", "private-repo"),
        system_score={"score": 60},
        detected_info={},
        private_mode=True,
        settings=make_settings(tavily_api_key="tavily-key"),
        github_client=FakeGithubClient(repo_name="private-repo"),
        llm=llm,
        tavily=tavily,
        permissions={},
    )

    assert result["tavily_enabled"] is False
    assert "tavily.search" not in result["used_tools"]
    assert "tavily.search" not in result["attempted_tools"]
    assert result["tool_errors"] == []
    assert "不使用 Tavily" in llm.prompts[0]
    assert "不向公开网页工具发送私有数据" in llm.prompts[0]


def test_run_agent_analysis_private_mode_collects_enhanced_github_tools():
    github_client = FakeGithubClient(repo_name="private-repo")
    llm = FakeLlm(
        {
            "ai_score": 76,
            "confidence": "medium",
            "summary": "private enhanced analysis",
            "findings": [],
            "recommendations": [],
            "references": [],
        }
    )

    result = run_agent_analysis(
        repo_url="https://github.com/owner/private-repo",
        ref=RepoRef("owner", "private-repo"),
        system_score={"score": 70},
        detected_info={},
        private_mode=True,
        settings=make_settings(tavily_api_key="tavily-key"),
        github_client=github_client,
        llm=llm,
        tavily=ExplodingTavily(),
        permissions={
            "actions": "read",
            "administration": "read",
            "checks": "read",
            "contents": "read",
            "deployments": "read",
            "issues": "read",
            "pull_requests": "read",
            "repository_advisories": "read",
            "vulnerability_alerts": "read",
            "security_events": "read",
            "secret_scanning_alerts": "read",
        },
    )

    assert result["tavily_enabled"] is False
    assert result["attempted_tools"] == [
        "github.get_repo_summary",
        "github.get_language_breakdown",
        "github.get_community_profile",
        "github.get_recent_commits",
        "github.get_issues_summary",
        "github.get_pulls_summary",
        "github.get_releases",
        "github.get_actions_runs_summary",
        "github.get_readme_and_key_files",
        "github.get_traffic_summary",
        "github.get_sbom_summary",
        "github.get_dependabot_alerts_summary",
        "github.get_code_scanning_alerts_summary",
        "github.get_secret_scanning_alerts_summary",
        "github.get_checks_summary",
        "github.get_repository_rules_summary",
        "github.get_security_advisories_summary",
        "github.get_deployments_summary",
    ]
    assert "github.get_traffic_summary" in result["used_tools"]
    assert "github.get_sbom_summary" in result["used_tools"]
    assert "github.get_dependabot_alerts_summary" in result["used_tools"]
    assert "github.get_code_scanning_alerts_summary" in result["used_tools"]
    assert "github.get_secret_scanning_alerts_summary" in result["used_tools"]
    assert "github.get_checks_summary" in result["used_tools"]
    assert "github.get_repository_rules_summary" in result["used_tools"]
    assert "github.get_security_advisories_summary" in result["used_tools"]
    assert "github.get_deployments_summary" in result["used_tools"]
    assert "traffic" in llm.prompts[0]
    assert "dependabot" in llm.prompts[0]
    assert "secret_scanning" in llm.prompts[0]
    assert github_client.calls == [
        ("/repos/owner/private-repo", None),
        ("/repos/owner/private-repo/languages", None),
        ("/repos/owner/private-repo/community/profile", None),
        ("/repos/owner/private-repo/commits", {"per_page": 30}),
        ("/repos/owner/private-repo/issues", {"state": "open", "per_page": 30}),
        ("/repos/owner/private-repo/pulls", {"state": "open", "per_page": 30}),
        ("/repos/owner/private-repo/releases", {"per_page": 10}),
        ("/repos/owner/private-repo/actions/runs", {"per_page": 20}),
        ("/repos/owner/private-repo/readme", None),
        ("/repos/owner/private-repo/contents/CONTRIBUTING.md", None),
        ("/repos/owner/private-repo/contents/SECURITY.md", None),
        ("/repos/owner/private-repo/contents/CODE_OF_CONDUCT.md", None),
        ("/repos/owner/private-repo/traffic/views", None),
        ("/repos/owner/private-repo/traffic/clones", None),
        ("/repos/owner/private-repo/traffic/popular/referrers", None),
        ("/repos/owner/private-repo/traffic/popular/paths", None),
        ("/repos/owner/private-repo/dependency-graph/sbom/generate-report", None),
        ("/repos/owner/private-repo/dependabot/alerts", {"per_page": 100}),
        ("/repos/owner/private-repo/code-scanning/alerts", {"per_page": 100}),
        ("/repos/owner/private-repo/secret-scanning/alerts", {"per_page": 100}),
        ("/repos/owner/private-repo", None),
        ("/repos/owner/private-repo/commits/main/check-runs", {"per_page": 50}),
        ("/repos/owner/private-repo/rulesets", {"per_page": 30}),
        ("/repos/owner/private-repo/security-advisories", {"per_page": 50}),
        ("/repos/owner/private-repo/deployments", {"per_page": 30}),
    ]


def test_run_agent_analysis_private_mode_attempts_unavailable_tools_without_marking_used():
    github_client = FakeGithubClient(repo_name="private-repo")
    llm = FakeLlm(
        {
            "ai_score": 60,
            "confidence": "low",
            "summary": "limited private analysis",
            "findings": [],
            "recommendations": [],
            "references": [],
        }
    )

    result = run_agent_analysis(
        repo_url="https://github.com/owner/private-repo",
        ref=RepoRef("owner", "private-repo"),
        system_score={"score": 60},
        detected_info={},
        private_mode=True,
        settings=make_settings(tavily_api_key="tavily-key"),
        github_client=github_client,
        llm=llm,
        tavily=ExplodingTavily(),
        permissions={"contents": "read"},
    )

    assert "github.get_traffic_summary" in result["attempted_tools"]
    assert "github.get_dependabot_alerts_summary" in result["attempted_tools"]
    assert "github.get_code_scanning_alerts_summary" in result["attempted_tools"]
    assert "github.get_secret_scanning_alerts_summary" in result["attempted_tools"]
    assert "github.get_checks_summary" in result["attempted_tools"]
    assert "github.get_repository_rules_summary" in result["attempted_tools"]
    assert "github.get_security_advisories_summary" in result["attempted_tools"]
    assert "github.get_deployments_summary" in result["attempted_tools"]
    assert "github.get_traffic_summary" not in result["used_tools"]
    assert "github.get_dependabot_alerts_summary" not in result["used_tools"]
    assert "github.get_code_scanning_alerts_summary" not in result["used_tools"]
    assert "github.get_secret_scanning_alerts_summary" not in result["used_tools"]
    assert "github.get_checks_summary" not in result["used_tools"]
    assert "github.get_repository_rules_summary" not in result["used_tools"]
    assert "github.get_security_advisories_summary" not in result["used_tools"]
    assert "github.get_deployments_summary" not in result["used_tools"]
    assert "missing_permission" in llm.prompts[0]
    assert github_client.calls == [
        ("/repos/owner/private-repo", None),
        ("/repos/owner/private-repo/languages", None),
        ("/repos/owner/private-repo/community/profile", None),
        ("/repos/owner/private-repo/commits", {"per_page": 30}),
        ("/repos/owner/private-repo/releases", {"per_page": 10}),
        ("/repos/owner/private-repo/readme", None),
        ("/repos/owner/private-repo/contents/CONTRIBUTING.md", None),
        ("/repos/owner/private-repo/contents/SECURITY.md", None),
        ("/repos/owner/private-repo/contents/CODE_OF_CONDUCT.md", None),
        ("/repos/owner/private-repo/dependency-graph/sbom/generate-report", None),
    ]


def test_run_agent_analysis_records_tavily_tool_errors_without_blocking_llm():
    tavily = SearchFailingTavily()
    llm = FakeLlm(
        {
            "ai_score": 70,
            "confidence": "medium",
            "summary": "仅基于 GitHub 摘要分析。",
            "findings": [],
            "recommendations": [],
            "references": [],
        }
    )

    result = run_agent_analysis(
        repo_url="https://github.com/owner/repo",
        ref=RepoRef("owner", "repo"),
        system_score={"score": 70},
        detected_info={},
        private_mode=False,
        settings=make_settings(tavily_api_key="tavily-key"),
        github_client=FakeGithubClient(),
        llm=llm,
        tavily=tavily,
    )

    assert result["ai_score"] == 70
    assert result["tavily_enabled"] is True
    assert "tavily.search" in result["attempted_tools"]
    assert "tavily.search" not in result["used_tools"]
    assert result["tool_errors"] == [{"tool": "tavily.search", "message": "search unavailable"}]
    assert '"tool_errors"' in llm.prompts[0]


def test_run_agent_analysis_returns_raw_response_fallback_for_invalid_llm_json():
    result = run_agent_analysis(
        repo_url="https://github.com/owner/repo",
        ref=RepoRef("owner", "repo"),
        system_score={"score": 50},
        detected_info={},
        private_mode=False,
        settings=make_settings(tavily_api_key=None),
        github_client=FakeGithubClient(),
        llm=RawLlm("not json"),
    )

    assert result["ai_score"] is None
    assert result["agent_score"] is None
    assert result["confidence"] == "low"
    assert "无法解析" in result["summary"]
    assert result["raw_response"] == "not json"
    assert result["tavily_enabled"] is False


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_run_agent_analysis_rejects_non_finite_json_score_constants(constant):
    result = run_agent_analysis(
        repo_url="https://github.com/owner/repo",
        ref=RepoRef("owner", "repo"),
        system_score={"score": 50},
        detected_info={},
        private_mode=False,
        settings=make_settings(tavily_api_key=None),
        github_client=FakeGithubClient(),
        llm=RawLlm(
            f'{{"ai_score": {constant}, "confidence": "high", "summary": "bad score", '
            '"findings": [], "recommendations": [], "references": []}'
        ),
    )

    assert result["ai_score"] is None
    assert result["agent_score"] is None
    assert "无法解析" in result["summary"]


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, json, timeout, headers=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(self.payload)


class FakeGithubClient:
    def __init__(self, repo_name: str = "repo"):
        self.repo_name = repo_name
        self.calls = []

    def get_json(self, path, params=None):
        self.calls.append((path, params))
        base = f"/repos/owner/{self.repo_name}"
        readme_text = "# Repo\nDocs"
        contributing_text = "Contributing"
        security_text = "Security policy"
        conduct_text = "Code of conduct"
        fixtures = {
            base: {
                "full_name": f"owner/{self.repo_name}",
                "stargazers_count": 100,
                "forks_count": 12,
                "open_issues_count": 5,
                "archived": False,
                "fork": False,
                "default_branch": "main",
                "license": {"spdx_id": "MIT"},
            },
            f"{base}/languages": {"Python": 900, "HTML": 100},
            f"{base}/community/profile": {
                "health_percentage": 90,
                "files": {
                    "readme": {"name": "README.md"},
                    "license": {"name": "LICENSE"},
                    "contributing": {"name": "CONTRIBUTING.md"},
                    "code_of_conduct": {"name": "CODE_OF_CONDUCT.md"},
                    "issue_template": None,
                    "pull_request_template": None,
                    "security": {"name": "SECURITY.md"},
                },
            },
            f"{base}/commits": [
                {
                    "sha": "abc123456789",
                    "author": {"login": "octocat"},
                    "commit": {
                        "message": "Initial commit\n\nbody",
                        "author": {"name": "Octocat", "date": "2026-05-01T00:00:00Z"},
                    },
                    "html_url": f"https://github.com/owner/{self.repo_name}/commit/abc123456789",
                }
            ],
            f"{base}/issues": [
                {
                    "number": 1,
                    "title": "Issue",
                    "state": "open",
                    "created_at": "2026-05-02T00:00:00Z",
                    "updated_at": "2026-05-03T00:00:00Z",
                    "labels": [{"name": "bug"}],
                    "html_url": f"https://github.com/owner/{self.repo_name}/issues/1",
                }
            ],
            f"{base}/pulls": [
                {
                    "number": 2,
                    "title": "PR",
                    "state": "open",
                    "draft": False,
                    "created_at": "2026-05-04T00:00:00Z",
                    "updated_at": "2026-05-05T00:00:00Z",
                    "html_url": f"https://github.com/owner/{self.repo_name}/pull/2",
                }
            ],
            f"{base}/releases": [
                {
                    "tag_name": "v1.0.0",
                    "name": "Version 1",
                    "published_at": "2026-05-01T00:00:00Z",
                    "prerelease": False,
                    "draft": False,
                    "html_url": f"https://github.com/owner/{self.repo_name}/releases/tag/v1.0.0",
                }
            ],
            f"{base}/readme": {
                "name": "README.md",
                "path": "README.md",
                "size": len(readme_text),
                "encoding": "base64",
                "content": base64.b64encode(readme_text.encode()).decode(),
                "html_url": f"https://github.com/owner/{self.repo_name}/blob/main/README.md",
            },
            f"{base}/contents/CONTRIBUTING.md": {
                "name": "CONTRIBUTING.md",
                "path": "CONTRIBUTING.md",
                "size": len(contributing_text),
                "encoding": "base64",
                "content": base64.b64encode(contributing_text.encode()).decode(),
                "html_url": f"https://github.com/owner/{self.repo_name}/blob/main/CONTRIBUTING.md",
            },
            f"{base}/contents/SECURITY.md": {
                "name": "SECURITY.md",
                "path": "SECURITY.md",
                "size": len(security_text),
                "encoding": "base64",
                "content": base64.b64encode(security_text.encode()).decode(),
                "html_url": f"https://github.com/owner/{self.repo_name}/blob/main/SECURITY.md",
            },
            f"{base}/contents/CODE_OF_CONDUCT.md": {
                "name": "CODE_OF_CONDUCT.md",
                "path": "CODE_OF_CONDUCT.md",
                "size": len(conduct_text),
                "encoding": "base64",
                "content": base64.b64encode(conduct_text.encode()).decode(),
                "html_url": f"https://github.com/owner/{self.repo_name}/blob/main/CODE_OF_CONDUCT.md",
            },
            f"{base}/actions/runs": {
                "total_count": 1,
                "workflow_runs": [
                    {
                        "id": 1,
                        "name": "CI",
                        "status": "completed",
                        "conclusion": "success",
                        "event": "push",
                        "created_at": "2026-05-01T00:00:00Z",
                        "updated_at": "2026-05-01T00:01:00Z",
                        "html_url": f"https://github.com/owner/{self.repo_name}/actions/runs/1",
                    }
                ],
            },
            f"{base}/traffic/views": {"count": 10, "uniques": 4, "views": [{"count": 1}]},
            f"{base}/traffic/clones": {"count": 6, "uniques": 3, "clones": [{"count": 1}]},
            f"{base}/traffic/popular/referrers": [
                {"referrer": "github.com", "count": 5, "uniques": 2, "extra": "drop"}
            ],
            f"{base}/traffic/popular/paths": [
                {"path": "/owner/private-repo", "title": "repo", "count": 8, "uniques": 3, "extra": "drop"}
            ],
            f"{base}/dependency-graph/sbom/generate-report": {
                "sbom": {"packages": [{"name": "flask", "versionInfo": "3.0.0"}]},
                "sbom_url": "https://api.github.com/repos/owner/private-repo/dependency-graph/sbom/fetch-report/1",
            },
            f"{base}/dependabot/alerts": [
                {
                    "number": 1,
                    "state": "open",
                    "dependency": {"package": {"name": "flask", "ecosystem": "pip"}},
                    "security_vulnerability": {"severity": "high"},
                    "security_advisory": {"summary": "drop"},
                }
            ],
            f"{base}/code-scanning/alerts": [
                {
                    "number": 2,
                    "state": "dismissed",
                    "rule": {"id": "py/sql-injection", "severity": "error"},
                    "tool": {"name": "CodeQL"},
                    "most_recent_instance": {"message": {"text": "drop"}},
                }
            ],
            f"{base}/secret-scanning/alerts": [
                {
                    "number": 3,
                    "state": "open",
                    "secret_type": "github_personal_access_token",
                    "secret": "drop-secret",
                }
            ],
            f"{base}/commits/main/check-runs": {
                "total_count": 1,
                "check_runs": [
                    {
                        "id": 4,
                        "name": "CI",
                        "status": "completed",
                        "conclusion": "success",
                        "started_at": "2026-05-01T00:00:00Z",
                        "completed_at": "2026-05-01T00:01:00Z",
                        "html_url": f"https://github.com/owner/{self.repo_name}/runs/4",
                        "output": {"summary": "drop"},
                    }
                ],
            },
            f"{base}/rulesets": [
                {
                    "id": 1,
                    "name": "main protection",
                    "target": "branch",
                    "enforcement": "active",
                    "source_type": "Repository",
                    "rules": [{"type": "required_status_checks"}],
                }
            ],
            f"{base}/security-advisories": [
                {
                    "ghsa_id": "GHSA-abcd-1234-efgh",
                    "cve_id": "CVE-2026-0001",
                    "state": "published",
                    "severity": "high",
                    "description": "drop",
                    "published_at": "2026-05-01T00:00:00Z",
                    "updated_at": "2026-05-02T00:00:00Z",
                    "html_url": f"https://github.com/owner/{self.repo_name}/security/advisories/GHSA-abcd-1234-efgh",
                }
            ],
            f"{base}/deployments": [
                {
                    "id": 9,
                    "environment": "production",
                    "ref": "main",
                    "sha": "abc123456789",
                    "task": "deploy",
                    "created_at": "2026-05-01T00:00:00Z",
                    "updated_at": "2026-05-01T00:02:00Z",
                    "transient_environment": False,
                    "production_environment": True,
                    "payload": {"drop": True},
                }
            ],
        }
        return fixtures[path]


class FakeTavily:
    def __init__(self):
        self.queries = []
        self.extract_calls = []

    def search(self, query, max_results=5):
        self.queries.append({"query": query, "max_results": max_results})
        return [
            {
                "title": "Docs",
                "url": "https://docs.example.test",
                "content": "External evidence",
                "score": 0.9,
            }
        ]

    def extract(self, urls, query=None):
        self.extract_calls.append({"urls": urls, "query": query})
        return {
            "results": [
                {
                    "url": "https://docs.example.test",
                    "title": "Docs",
                    "content": "Extracted docs",
                    "raw_content": "Extracted raw docs",
                }
            ],
            "failed_results": [],
        }


class ExplodingTavily:
    def search(self, query, max_results=5):
        raise AssertionError("private mode must not call Tavily")


class SearchFailingTavily:
    def search(self, query, max_results=5):
        raise RuntimeError("search unavailable")

    def extract(self, urls, query=None):
        raise AssertionError("extract must not run after failed search")


class FakeLlm:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def complete_json(self, prompt):
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


class RawLlm:
    def __init__(self, raw_response):
        self.raw_response = raw_response

    def complete_json(self, prompt):
        return self.raw_response


def make_settings(tavily_api_key: str | None):
    return SimpleNamespace(
        tavily_api_key=tavily_api_key,
        model_base_url="https://model.example.test/v1",
        model_api_key="model-key",
        model_name="model-a",
    )
