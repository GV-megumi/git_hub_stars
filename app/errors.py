from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(
        self,
        message: str,
        github_status_code: int | None = None,
        github_path: str | None = None,
        github_message: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.github_status_code = github_status_code
        self.github_path = github_path
        self.github_message = github_message

    def to_dict(self) -> dict[str, object]:
        payload = {"error": self.code, "message": self.message}
        if self.github_status_code is not None:
            payload["github_status_code"] = self.github_status_code
        if self.github_path is not None:
            payload["github_path"] = self.github_path
        if self.github_message is not None:
            payload["github_message"] = self.github_message
        return payload


class ValidationError(AppError):
    status_code = 400
    code = "validation_error"


class GithubApiError(AppError):
    status_code = 502
    code = "github_api_error"


class GithubRateLimitError(GithubApiError):
    status_code = 429
    code = "github_rate_limit"

    def __init__(
        self,
        message: str,
        github_status_code: int | None = None,
        github_path: str | None = None,
        github_message: str | None = None,
        rate_limit_remaining: str | None = None,
        rate_limit_reset: str | None = None,
        retry_after: str | None = None,
    ):
        super().__init__(
            message,
            github_status_code=github_status_code,
            github_path=github_path,
            github_message=github_message,
        )
        self.rate_limit_remaining = rate_limit_remaining
        self.rate_limit_reset = rate_limit_reset
        self.retry_after = retry_after

    def to_dict(self) -> dict[str, object]:
        payload = super().to_dict()
        if self.rate_limit_remaining is not None:
            payload["rate_limit_remaining"] = self.rate_limit_remaining
        if self.rate_limit_reset is not None:
            payload["rate_limit_reset"] = self.rate_limit_reset
        if self.retry_after is not None:
            payload["retry_after"] = self.retry_after
        return payload


class LlmProviderError(AppError):
    status_code = 502
    code = "llm_provider_error"

    def __init__(
        self,
        message: str,
        provider_status_code: int | None = None,
        provider_error_code: str | None = None,
        provider_error_type: str | None = None,
        provider_message: str | None = None,
    ):
        super().__init__(message)
        self.provider_status_code = provider_status_code
        self.provider_error_code = provider_error_code
        self.provider_error_type = provider_error_type
        self.provider_message = provider_message

    def to_dict(self) -> dict[str, object]:
        payload = super().to_dict()
        if self.provider_status_code is not None:
            payload["provider_status_code"] = self.provider_status_code
        if self.provider_error_code is not None:
            payload["provider_error_code"] = self.provider_error_code
        if self.provider_error_type is not None:
            payload["provider_error_type"] = self.provider_error_type
        if self.provider_message is not None:
            payload["provider_message"] = self.provider_message
        return payload


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class PermissionRequiredError(AppError):
    status_code = 403
    code = "permission_required"
