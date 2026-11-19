"""Shared calendar reads in a disposable synthetic PostgreSQL schema."""
from __future__ import annotations

import os
import uuid
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.calendar_models import CalendarSessionRevision, CalendarVersion
from app.config import settings
from app.models import AppState
from app.read.calendar import head_version, latest_revision, latest_revisions

pytestmark = pytest.mark.integration


def _guard_url() -> str:
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL", "")
    parsed = make_url(url)
    assert settings.app_mode == "test"
    assert parsed.drivername in ("postgresql+psycopg", "postgresql")
    assert parsed.host in ("localhost", "127.0.0.1")
    assert parsed.port == int(os.environ.get('TEST_DATABASE_PORT', '55439')) and parsed.database == "mvp1_migration_test"
    return url


@pytest.fixture
def db(metrics_disabled):
    engine = create_engine(_guard_url())
    schema = "read_cal_" + uuid.uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.commit()
            yield sessionmaker(bind=connection, expire_on_commit=False)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def _revision(
    uid: uuid.UUID, revision: int, version: int, day: int, *, deleted: bool = False, intent: str = "x",
) -> CalendarSessionRevision:
    return CalendarSessionRevision(
        session_uid=uid, revision=revision, calendar_version_number=version,
        local_date=date(2026, 11, day), kind="run", slot=0, intent=intent, certainty="committed", deleted=deleted,
    )


def _seed(session) -> tuple[uuid.UUID, uuid.UUID]:
    state = session.get(AppState, 1)
    assert state is not None
    session.add_all([
        CalendarVersion(number=n, parent_number=n - 1 or None, kind="bootstrap" if n == 1 else "manual_edit",
                        actor="system")
        for n in range(1, 4)
    ])
    state.calendar_head_version = 3
    session.flush()

    uid_a, uid_b = uuid.uuid4(), uuid.uuid4()
    session.add_all([
        _revision(uid_a, 1, 1, 19),
        _revision(uid_a, 2, 2, 19, intent="edited"),
        _revision(uid_b, 1, 1, 20),
        _revision(uid_b, 2, 3, 20, deleted=True),
    ])
    session.flush()
    return uid_a, uid_b


def test_head_version_reads_app_state(db):
    with db() as session:
        _seed(session)
        assert head_version(session) == 3
        state = session.get(AppState, 1)
        assert state is not None
        state.calendar_head_version = 0
        assert head_version(session) == 0


def test_latest_revisions_defaults_to_head_and_keeps_deleted(db):
    with db() as session:
        uid_a, uid_b = _seed(session)

        rows = latest_revisions(session)
        assert rows[uid_a].revision == 2 and rows[uid_a].intent == "edited"
        assert rows[uid_b].revision == 2 and rows[uid_b].deleted


def test_latest_revisions_at_older_version(db):
    with db() as session:
        uid_a, uid_b = _seed(session)

        assert {uid: row.revision for uid, row in latest_revisions(session, 1).items()} == {uid_a: 1, uid_b: 1}
        rows = latest_revisions(session, 2)
        assert rows[uid_a].revision == 2
        assert rows[uid_b].revision == 1 and not rows[uid_b].deleted
        assert latest_revisions(session, 0) == {}


def test_latest_revision_single_session(db):
    with db() as session:
        uid_a, _ = _seed(session)

        current = latest_revision(session, uid_a)
        older = latest_revision(session, uid_a, 1)
        assert current is not None and current.revision == 2
        assert older is not None and older.revision == 1
        assert latest_revision(session, uuid.uuid4()) is None
        state = session.get(AppState, 1)
        assert state is not None
        state.calendar_head_version = 0
        assert latest_revision(session, uid_a) is None
