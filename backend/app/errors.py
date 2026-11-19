"""Domain error raised by services and routes; `main.handle_http` renders it as the error envelope."""
from __future__ import annotations

from typing import Any, NoReturn

from fastapi import HTTPException


class AppError(HTTPException):
    """A failure with a stable `code`. Routes render it through `handle_http`; the CLI maps it to an exit status."""

    def __init__(self, code: str, message: str, status: int = 422,
                 fields: list[dict[str, Any]] | None = None) -> None:
        detail: dict[str, Any] = {'code': code, 'message': message}
        if fields:
            detail['fields'] = fields
        super().__init__(status_code=status, detail=detail)
        self.code = code
        self.message = message
        self.fields = fields or []


def fail(code: str, message: str, status: int = 422) -> NoReturn:
    raise AppError(code, message, status)
