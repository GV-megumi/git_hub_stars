from __future__ import annotations

import json
import math
from typing import Any

from app.agent.llm import LlmClient
from app.agent.tavily import TavilyClient
from app.agent.tools import GithubAgentTools
from app.errors import AppError
from app.github.client import GithubClient
from app.github.url_parser import RepoRef


_TOOL_CALLS = (
    ("github.get_repo_summary", "repo_summary", "get_repo_summary"),
    ("github.get_language_breakdown", "languages", "get_language_breakdown"),
    ("github.get_releases", "releases", "get_releases"),
    ("github.get_actions_runs_summary", "actions", "get_actions_runs_summary"),
)

_PRIVATE_TOOL_CALLS = (
    ("github.get_traffic_summary", "traffic", "get_traffic_summary"),
    ("github.get_sbom_summary", "sbom", "get_sbom_summary"),
    ("github.get_dependabot_alerts_summary", "dependabot", "get_dependabot_alerts_summary"),
    ("github.get_code_scanning_alerts_summary", "code_scanning", "get_code_scanning_alerts_summary"),
    ("github.get_secret_scanning_alerts_summary", "secret_scanning", "get_secret_scanning_alerts_summary"),
)


def should_enable_tavily(private_mode: bool, tavily_api_key: str | None) -> bool:
    return not private_mode and bool(tavily_api_key and tavily_api_key.strip())


def build_agent_prompt(
    repo_url: str,
    system_score: dict[str, Any],
    private_mode: bool,
    detected_info: dict[str, Any] | None = None,
    github_context: dict[str, Any] | None = None,
    tavily_context: dict[str, Any] | None = None,
) -> str:
    if private_mode:
        mode_guidance = (
            "私有仓库模式：不使用 Tavily；不向公开网页工具发送私有数据；"
            "只使用服务端提供的受控 GitHub API 摘要和用户已确认可发送给模型的信息。"
        )
    else:
        mode_guidance = "公开仓库模式：可以结合受控 GitHub API 摘要和 Tavily 公开网页证据。"

    return "\n".join(
        [
            "你是 Github 仓库健康分析 agent。请用中文分析仓库健康度，并只输出 JSON。",
            f"仓库链接：{repo_url}",
            f"仓库模式：{mode_guidance}",
            f"系统评分：{_json(system_score)}",
            f"基础探测信息：{_json(detected_info or {})}",
            f"GitHub 工具摘要：{_json(github_context or {})}",
            f"Tavily 证据：{_json(tavily_context or {})}",
            "判断系统评分是否遗漏了重要背景；公开信息不足时请降低 confidence，不要编造。",
            (
                "输出 JSON 对象，字段必须包含：ai_score（0-100 数字）、confidence、summary、"
                "findings、recommendations、references。findings 和 references 使用数组。"
            ),
        ]
    )


def run_agent_analysis(
    *,
    repo_url: str,
    ref: RepoRef,
    system_score: dict[str, Any],
    detected_info: dict[str, Any] | None,
    private_mode: bool,
    settings: Any,
    github_client: GithubClient,
    llm: LlmClient | None = None,
    tavily: TavilyClient | None = None,
    permissions: dict[str, str] | None = None,
) -> dict[str, Any]:
    attempted_tools: list[str] = []
    used_tools: list[str] = []
    tool_errors: list[dict[str, str]] = []
    github_context = _collect_github_context(
        github_client=github_client,
        ref=ref,
        private_mode=private_mode,
        permissions=permissions or {},
        attempted_tools=attempted_tools,
        used_tools=used_tools,
        tool_errors=tool_errors,
    )

    tavily_enabled = should_enable_tavily(private_mode, getattr(settings, "tavily_api_key", None))
    tavily_context: dict[str, Any]
    if tavily_enabled:
        tavily_client = tavily or TavilyClient(settings.tavily_api_key)
        query = _build_tavily_query(repo_url, github_context, detected_info or {})
        tavily_context = _collect_tavily_context(
            tavily_client=tavily_client,
            query=query,
            attempted_tools=attempted_tools,
            used_tools=used_tools,
            tool_errors=tool_errors,
        )
    else:
        reason = "private_mode" if private_mode else "missing_tavily_api_key"
        tavily_context = {"enabled": False, "reason": reason}

    prompt = build_agent_prompt(
        repo_url=repo_url,
        system_score=system_score,
        private_mode=private_mode,
        detected_info=detected_info or {},
        github_context=github_context,
        tavily_context=tavily_context,
    )
    llm_client = llm or LlmClient(
        base_url=settings.model_base_url,
        api_key=settings.model_api_key,
        model=settings.model_name,
    )
    raw_response = llm_client.complete_json(prompt)
    parsed = _parse_json_object(raw_response)
    if parsed is None:
        return _raw_response_fallback(raw_response, used_tools, attempted_tools, tool_errors, tavily_enabled)

    return _normalize_agent_output(parsed, used_tools, attempted_tools, tool_errors, tavily_enabled)


def _collect_github_context(
    *,
    github_client: GithubClient,
    ref: RepoRef,
    private_mode: bool,
    permissions: dict[str, str],
    attempted_tools: list[str],
    used_tools: list[str],
    tool_errors: list[dict[str, str]],
) -> dict[str, Any]:
    tools = GithubAgentTools(github_client, ref, private_mode=private_mode, permissions=permissions)
    context: dict[str, Any] = {}
    tool_calls = _TOOL_CALLS + (_PRIVATE_TOOL_CALLS if private_mode else ())
    for tool_name, context_key, method_name in tool_calls:
        method = getattr(tools, method_name)
        attempted_tools.append(tool_name)
        try:
            result = method()
            context[context_key] = result
        except AppError as exc:
            context[context_key] = {"available": False, "error": exc.code, "message": exc.message}
            tool_errors.append({"tool": tool_name, "message": exc.message})
        else:
            if _tool_result_available(result):
                used_tools.append(tool_name)
    return context


def _tool_result_available(result: Any) -> bool:
    return not (isinstance(result, dict) and result.get("available") is False)


def _collect_tavily_context(
    *,
    tavily_client: TavilyClient,
    query: str,
    attempted_tools: list[str],
    used_tools: list[str],
    tool_errors: list[dict[str, str]],
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "enabled": True,
        "search_results": [],
        "extracted_results": [],
    }
    tavily_errors: list[dict[str, str]] = []

    attempted_tools.append("tavily.search")
    try:
        search_results = tavily_client.search(query, max_results=5)
    except Exception as exc:  # Tavily is supplemental; do not block GitHub analysis.
        error = _tool_error("tavily.search", exc)
        tool_errors.append(error)
        tavily_errors.append(error)
        context["search_error"] = error["message"]
        context["tool_errors"] = tavily_errors
        return context

    used_tools.append("tavily.search")
    context["search_results"] = search_results
    urls = _search_result_urls(search_results, limit=3)
    if not urls:
        return context

    attempted_tools.append("tavily.extract")
    try:
        extracted = tavily_client.extract(urls, query=query)
    except Exception as exc:  # Tavily is supplemental; do not block GitHub analysis.
        error = _tool_error("tavily.extract", exc)
        tool_errors.append(error)
        tavily_errors.append(error)
        context["extract_error"] = error["message"]
        context["tool_errors"] = tavily_errors
        return context

    used_tools.append("tavily.extract")
    if isinstance(extracted, dict):
        context["extracted_results"] = _bounded_list(extracted.get("results"), limit=20)
        context["extract_failed_results"] = _bounded_list(extracted.get("failed_results"), limit=20)
    return context


def _tool_error(tool_name: str, exc: Exception) -> dict[str, str]:
    return {"tool": tool_name, "message": str(exc)}


def _search_result_urls(search_results: Any, limit: int) -> list[str]:
    urls: list[str] = []
    for item in _bounded_list(search_results, limit=limit):
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if isinstance(url, str) and url.strip():
            urls.append(url.strip())
    return urls


def _bounded_list(value: Any, limit: int) -> list[Any]:
    return value[:limit] if isinstance(value, list) else []


def _build_tavily_query(repo_url: str, github_context: dict[str, Any], detected_info: dict[str, Any]) -> str:
    repo_summary = github_context.get("repo_summary")
    full_name = repo_summary.get("full_name") if isinstance(repo_summary, dict) else None
    query_parts = [
        str(full_name or repo_url),
        "GitHub repository health maintenance releases documentation community discussion",
    ]
    description = detected_info.get("description") if isinstance(detected_info, dict) else None
    if isinstance(description, str) and description.strip():
        query_parts.append(description.strip())
    return " ".join(query_parts)[:400]


def _parse_json_object(raw_response: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw_response, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError):
        parsed = _parse_embedded_json_object(raw_response)
    return parsed if isinstance(parsed, dict) else None


def _parse_embedded_json_object(raw_response: str) -> Any:
    start = raw_response.find("{")
    end = raw_response.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(raw_response[start : end + 1], parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError):
        return None


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _normalize_agent_output(
    parsed: dict[str, Any],
    used_tools: list[str],
    attempted_tools: list[str],
    tool_errors: list[dict[str, str]],
    tavily_enabled: bool,
) -> dict[str, Any]:
    ai_score = _coerce_score(parsed.get("ai_score", parsed.get("agent_score")))
    output = {
        "ai_score": ai_score,
        "agent_score": ai_score,
        "confidence": _coerce_string(parsed.get("confidence"), default="low"),
        "summary": _coerce_string(parsed.get("summary"), default="模型未返回摘要。"),
        "findings": _coerce_list(parsed.get("findings")),
        "recommendations": _coerce_list(parsed.get("recommendations")),
        "references": _coerce_list(parsed.get("references")),
        "used_tools": used_tools,
        "attempted_tools": attempted_tools,
        "tool_errors": tool_errors,
        "tavily_enabled": tavily_enabled,
    }
    return output


def _raw_response_fallback(
    raw_response: str,
    used_tools: list[str],
    attempted_tools: list[str],
    tool_errors: list[dict[str, str]],
    tavily_enabled: bool,
) -> dict[str, Any]:
    return {
        "ai_score": None,
        "agent_score": None,
        "confidence": "low",
        "summary": "模型返回的 JSON 无法解析。",
        "findings": [
            {
                "level": "error",
                "title": "LLM 输出不是有效 JSON",
                "detail": "请检查模型配置或重试。",
            }
        ],
        "recommendations": [],
        "references": [],
        "used_tools": used_tools,
        "attempted_tools": attempted_tools,
        "tool_errors": tool_errors,
        "tavily_enabled": tavily_enabled,
        "raw_response": raw_response[:4000],
    }


def _coerce_score(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return max(0, min(100, value))


def _coerce_string(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value.strip() else default


def _coerce_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
