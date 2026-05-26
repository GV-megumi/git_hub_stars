from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "app_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}


class ValidationError(AppError):
    status_code = 400
    code = "validation_error"


class GithubApiError(AppError):
    status_code = 502
    code = "github_api_error"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class PermissionRequiredError(AppError):
    status_code = 403
    code = "permission_required"
