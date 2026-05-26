from __future__ import annotations

from typing import Any

import requests


_SEARCH_URL = "https://api.tavily.com/search"
_EXTRACT_URL = "https://api.tavily.com/extract"
_SEARCH_RESULT_FIELDS = ("title", "url", "content", "score")
_EXTRACT_RESULT_FIELDS = ("url", "title", "content", "raw_content")
_FAILED_RESULT_FIELDS = ("url", "error", "status")
_MAX_QUERY_LENGTH = 400
_MAX_TEXT_FIELD_LENGTH = 1200


class TavilyClient:
    def __init__(self, api_key: str, session: Any = requests):
        self.api_key = api_key
        self.session = session

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        max_results = _bounded_int(max_results, default=5, minimum=1, maximum=10)
        response = self.session.post(
            _SEARCH_URL,
            headers=self._headers(),
            json={
                "query": _bounded_query(query),
                "search_depth": "basic",
                "max_results": max_results,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return [_select_fields(item, _SEARCH_RESULT_FIELDS) for item in results[:max_results] if isinstance(item, dict)]

    def extract(self, urls: list[str], query: str | None = None) -> dict[str, list[dict[str, Any]]]:
        bounded_urls = [url for url in urls if isinstance(url, str) and url.strip()][:20]
        response = self.session.post(
            _EXTRACT_URL,
            headers=self._headers(),
            json={
                "urls": bounded_urls,
                "extract_depth": "basic",
                "query": _bounded_query(query) if query is not None else None,
                "chunks_per_source": 3,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {"results": [], "failed_results": []}

        results = payload.get("results", [])
        failed_results = payload.get("failed_results", [])
        return {
            "results": [
                _select_fields(item, _EXTRACT_RESULT_FIELDS)
                for item in _bounded_list(results, limit=20)
                if isinstance(item, dict)
            ],
            "failed_results": [
                _select_fields(item, _FAILED_RESULT_FIELDS)
                for item in _bounded_list(failed_results, limit=20)
                if isinstance(item, dict)
            ],
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


def _select_fields(data: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    for field in fields:
        if field not in data:
            continue
        value = data.get(field)
        if field in {"content", "raw_content"} and isinstance(value, str):
            value = value[:_MAX_TEXT_FIELD_LENGTH]
        selected[field] = value
    return selected


def _bounded_query(query: Any) -> str:
    if not isinstance(query, str):
        return ""
    return query[:_MAX_QUERY_LENGTH]


def _bounded_list(value: Any, limit: int) -> list[Any]:
    return value[:limit] if isinstance(value, list) else []


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(minimum, min(maximum, value))
