from __future__ import annotations

import re
from typing import Any

from openai import APIStatusError, BadRequestError, OpenAI

from app.errors import LlmProviderError

_SAFE_PROVIDER_MESSAGE_CODES = {"model_not_found"}
_SECRET_PATTERNS = (
    re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(api[_-]?key\s*[=:]\s*)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(token\s*[=:]\s*)[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9_-]+"),
)


class LlmClient:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def complete_json(self, prompt: str) -> str:
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是 Github 仓库健康分析 agent，只输出 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self.client.chat.completions.create(**kwargs)
        except TypeError as exc:
            if not _is_response_format_unsupported(exc):
                raise
            kwargs.pop("response_format", None)
            try:
                response = self.client.chat.completions.create(**kwargs)
            except (BadRequestError, APIStatusError) as retry_exc:
                raise _llm_provider_error(retry_exc) from retry_exc
        except (BadRequestError, APIStatusError) as exc:
            if not _is_response_format_unsupported(exc):
                raise _llm_provider_error(exc) from exc
            kwargs.pop("response_format", None)
            try:
                response = self.client.chat.completions.create(**kwargs)
            except APIStatusError as retry_exc:
                raise _llm_provider_error(retry_exc) from retry_exc
        return response.choices[0].message.content or "{}"


def _is_response_format_unsupported(exc: Exception) -> bool:
    parts: list[Any] = [str(exc)]
    body = getattr(exc, "body", None)
    if body is not None:
        parts.append(body)
    message = " ".join(str(part) for part in parts).lower()
    return "response_format" in message or "json_object" in message


def _llm_provider_error(exc: Exception) -> LlmProviderError:
    body = _provider_error_body(exc)
    provider_error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(provider_error, dict):
        provider_error = body if _looks_like_provider_error(body) else {}
    provider_message = provider_error.get("message")
    provider_error_code = provider_error.get("code")
    provider_error_type = provider_error.get("type")
    safe_provider_message = _safe_provider_message(provider_error_code, provider_message)
    return LlmProviderError(
        "AI model request failed. Check MODEL_NAME, MODEL_BASE_URL, and provider availability.",
        provider_status_code=getattr(exc, "status_code", None),
        provider_error_code=provider_error_code if isinstance(provider_error_code, str) else None,
        provider_error_type=provider_error_type if isinstance(provider_error_type, str) else None,
        provider_message=safe_provider_message,
    )


def _provider_error_body(exc: Exception) -> Any:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        return body
    response = getattr(exc, "response", None)
    if response is None:
        return body
    try:
        parsed = response.json()
    except ValueError:
        return body
    return parsed


def _looks_like_provider_error(value: Any) -> bool:
    return isinstance(value, dict) and any(key in value for key in ("code", "message", "type"))


def _safe_provider_message(provider_error_code: object, provider_message: object) -> str | None:
    if not isinstance(provider_error_code, str) or provider_error_code not in _SAFE_PROVIDER_MESSAGE_CODES:
        return None
    if not isinstance(provider_message, str):
        return None
    sanitized = provider_message[:500]
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub(_redact_secret_match, sanitized)
    return sanitized


def _redact_secret_match(match: re.Match[str]) -> str:
    if match.lastindex:
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"
