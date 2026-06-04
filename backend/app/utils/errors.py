from flask import Flask, jsonify


class AppError(Exception):
    error_code = "APP_ERROR"
    status_code = 400

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    error_code = "NOT_FOUND"
    status_code = 404


class ValidationError(AppError):
    error_code = "VALIDATION_ERROR"
    status_code = 422


class UnauthorizedError(AppError):
    error_code = "UNAUTHORIZED"
    status_code = 401


class ForbiddenError(AppError):
    """403 — the request is authenticated but the resource state forbids it.
    Used for the email-not-verified login gate so the frontend can show a
    dedicated "verify your email" UI instead of the generic auth error."""

    error_code = "FORBIDDEN"
    status_code = 403


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def handle_app_error(err: AppError):
        return (
            jsonify(
                {
                    "error_code": err.error_code,
                    "message": err.message,
                    "details": err.details,
                }
            ),
            err.status_code,
        )
