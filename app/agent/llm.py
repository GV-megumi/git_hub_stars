from __future__ import annotations

from typing import Any

from openai import APIStatusError, BadRequestError, OpenAI


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
        except (TypeError, BadRequestError, APIStatusError) as exc:
            if not _is_response_format_unsupported(exc):
                raise
            kwargs.pop("response_format", None)
            response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or "{}"


def _is_response_format_unsupported(exc: Exception) -> bool:
    parts: list[Any] = [str(exc)]
    body = getattr(exc, "body", None)
    if body is not None:
        parts.append(body)
    message = " ".join(str(part) for part in parts).lower()
    return "response_format" in message or "json_object" in message
