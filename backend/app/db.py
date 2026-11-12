from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, select, text
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
    with session.no_autoflush:
        authority = session.scalar(select(AppState.planning_authority).where(AppState.id == 1))
    if authority == 'calendar':
        outer = session.get_transaction()
        if outer is None:
            outer = session.begin()
        marker = session.info.get('source_revision_bump')
        if marker is not None and marker[0] is outer:
            return marker[1]
        session.execute(text('SELECT pg_advisory_xact_lock(71382413)'))
        # Read the revision under the lock even if this identity was loaded
        # earlier, preserving other pending AppState fields (e.g. plan head).
        current = session.scalar(select(AppState.data_revision).where(AppState.id == 1).with_for_update())
        state = session.get(AppState, 1)
        assert state is not None and current is not None
        state.data_revision = current + 1
        session.flush()
        session.info['source_revision_bump'] = (outer, state.data_revision)
        return state.data_revision
    state = session.get(AppState, 1, with_for_update=True)
    if state is None:
        state = AppState(id=1, data_revision=0)
        session.add(state)
        session.flush()
    state.data_revision += 1
    session.flush()
    return state.data_revision


@event.listens_for(Session, 'after_transaction_create')
def _save_nested_revision_marker(session, transaction):
    if transaction.nested:
        transaction._source_revision_inherited = session.info.get('source_revision_bump')


@event.listens_for(Session, 'after_soft_rollback')
def _restore_nested_revision_marker(session, transaction):
    if transaction.nested:
        inherited = getattr(transaction, '_source_revision_inherited', None)
        if inherited is None:
            session.info.pop('source_revision_bump', None)
        else:
            session.info['source_revision_bump'] = inherited
    else:
        session.info.pop('source_revision_bump', None)


@event.listens_for(Session, 'after_transaction_end')
def _clear_outer_revision_marker(session, transaction):
    if transaction.parent is None:
        session.info.pop('source_revision_bump', None)


bump_revision = bump_data_revision
