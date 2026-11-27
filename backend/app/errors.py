"""Structured application errors for the Python reference services and CLI."""

from __future__ import annotations

from typing import Any, NoReturn


class AppError(Exception):
    """A failure with a stable code, message and optional field errors."""

    def __init__(self, code: str, message: str, status: int = 422, fields: list[dict[str, Any]] | None = None) -> None:
        detail: dict[str, Any] = {"code": code, "message": message}
        if fields:
            detail["fields"] = fields
        super().__init__(message)
        self.status_code = status
        self.detail = detail
        self.code = code
        self.message = message
        self.fields = fields or []


def fail(code: str, message: str, status: int = 422) -> NoReturn:
    raise AppError(code, message, status)
