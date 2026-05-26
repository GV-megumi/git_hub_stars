from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import BadRequestError

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


def test_llm_client_does_not_retry_unrelated_bad_request(monkeypatch):
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

    with pytest.raises(BadRequestError):
        client.complete_json("analyze this")
    assert len(create_calls) == 1


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
        "github.get_releases",
        "github.get_actions_runs_summary",
        "tavily.search",
        "tavily.extract",
    ]
    assert result["used_tools"] == [
        "github.get_repo_summary",
        "github.get_language_breakdown",
        "github.get_releases",
        "github.get_actions_runs_summary",
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
        ("/repos/owner/repo/releases", {"per_page": 10}),
        ("/repos/owner/repo/actions/runs", {"per_page": 20}),
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
