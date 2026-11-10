from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.api.core import get_context


def build_context(session: Session, as_of: date | None = None, include_notes: bool = False) -> dict:
    return get_context(as_of=as_of, include_notes=include_notes, session=session)['data']
