"""Error helper shared by services and routes; `main.handle_http` renders it."""
from __future__ import annotations

from typing import NoReturn

from fastapi import HTTPException


def fail(code: str, message: str, status: int = 422) -> NoReturn:
    raise HTTPException(status_code=status, detail={'code': code, 'message': message})
