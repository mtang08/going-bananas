from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def get_revision(session: Session) -> int:
    from app.models import AppState
    state = session.get(AppState, 1)
    return state.data_revision if state else 0


def bump_data_revision(session: Session) -> int:
    from app.models import AppState
    state = session.get(AppState, 1, with_for_update=True)
    if state is None:
        state = AppState(id=1, data_revision=0)
        session.add(state)
        session.flush()
    state.data_revision += 1
    session.flush()
    return state.data_revision


bump_revision = bump_data_revision
