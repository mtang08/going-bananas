"""Atomic training metric refresh against isolated, synthetic PostgreSQL schemas."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.checkin_models import SessionRpe
from app.config import settings
from app.db import bump_data_revision, get_revision
from app.metric_models import MetricResult, Prompt
from app.metrics import engine, refresh
from app.models import Activity, AppState, CoverageInterval, ProfileVersion
from app.services import derived
from app.services.metric_drilldowns import (
    activity_execution,
    explain_metric,
    long_run_history,
    metric_windows,
    recovery_nights,
)
from app.services.sync import import_activity_page

NOW = datetime(2025, 2, 2, 17, tzinfo=UTC)
TODAY = NOW.date()


def _guard_url() -> str:
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL", "")
    parsed = make_url(url)
    assert settings.app_mode == "test"
    assert parsed.drivername in ("postgresql+psycopg", "postgresql")
    assert parsed.host in ("localhost", "127.0.0.1")
    assert (
        parsed.port == int(os.environ.get("TEST_DATABASE_PORT", "55439")) and parsed.database == "mvp1_migration_test"
    )
    return url


@pytest.fixture
def db():
    engine = create_engine(_guard_url())
    schema = "mvp030_" + uuid.uuid4().hex
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
            yield sessionmaker(bind=connection, expire_on_commit=False, autoflush=False)
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def seed(db, tmp_path):
    derived.install()
    with db() as session:
        session.info["metrics_now"] = NOW
        session.add(
            ProfileVersion(
                version=1, effective_at=NOW, timezone="America/New_York", facts={}, preferences={}, unknowns=[]
            )
        )
        records = []
        for index, (day, timer, distance) in enumerate(
            [(27, 1800, 5000), (29, 2400, 6500), (31, 2100, 6000), (2, 3600, 10000)]
        ):
            stamp = datetime(2025, 2 if day == 2 else 1, day, 12, tzinfo=UTC)
            records.append(
                {
                    "activityId": 3000 + index,
                    "startTimeGMT": stamp.isoformat(),
                    "activityType": {"typeKey": "running"},
                    "duration": timer,
                    "distance": distance,
                }
            )
        import_activity_page(session, tmp_path, records, account_scope="synthetic-metrics", source_kind="demo_fixture")
        runs = list(session.scalars(select(Activity).order_by(Activity.start_at)))
        for row, timer in zip(runs, [1800, 2400, 2100, 3600], strict=True):
            row.timer_s = timer
            row.end_at = row.start_at + timedelta(seconds=timer)
        session.add(
            CoverageInterval(
                dataset="activities",
                start_date=date(2025, 1, 20),
                end_date=TODAY,
                status="complete",
                fully_enumerated=True,
                completed_at=NOW,
            )
        )
        session.add_all(
            [
                SessionRpe(activity_id=runs[1].id, rpe=6, source="garmin_fit", collected_at=NOW),
                SessionRpe(activity_id=runs[3].id, rpe=5, source="manual", collected_at=NOW),
            ]
        )
        session.commit()
        return [row.id for row in runs]


def counts(session):
    return tuple(session.scalar(select(func.count()).select_from(model)) for model in (MetricResult, Prompt))


def current(session, metric, key):
    return engine.current_results(session, metric, [key]).get(key)


def materialize(session):
    """Store today's windows before testing reads of persisted results."""
    refresh.ensure_windows(session, TODAY)
    session.commit()


def _statements(session, action) -> int:
    """SQL statements sent on this session's connection while `action` runs."""
    seen: list[str] = []
    connection = session.connection()

    def record(_conn, _cursor, statement, *_rest):
        seen.append(statement)

    event.listen(connection, "before_cursor_execute", record)
    try:
        action()
    finally:
        event.remove(connection, "before_cursor_execute", record)
    return len(seen)


def _move_plan(session, uid, number, day):
    """Commit calendar version `number` with one revision that puts session `uid` on `day`."""
    from app.calendar_models import CalendarSessionRevision, CalendarVersion

    session.add(CalendarVersion(number=number, kind="bootstrap" if number == 1 else "manual_edit", actor="system"))
    session.flush()
    session.add(
        CalendarSessionRevision(
            session_uid=uid,
            revision=number,
            calendar_version_number=number,
            local_date=day,
            kind="run",
            intent="Test run",
            planned_duration_s=3000,
            certainty="committed",
        )
    )
    session.get(AppState, 1).calendar_head_version = number
    session.commit()


def test_four_runs_idempotent_reads_and_explanation(db, tmp_path):
    ids = seed(db, tmp_path)
    with db() as session:
        session.info["metrics_now"] = NOW
        materialize(session)
        revision = get_revision(session)
        data = metric_windows(session, TODAY)
        assert set(data["aerobic"]) == {"w28", "w84"}
        volume = data["windows"][0]["volume"]
        assert volume["value"]["timer_duration_s"] == 9900
        assert volume["value"]["distance_m"] == 27500
        assert volume["value"]["run_count"] == 4
        rpe = data["windows"][0]["srpe"]["value"]
        assert rpe["load_au"] == 540
        assert rpe["coverage_duration"] == 0.606
        assert rpe["coverage_sessions"] == 0.5
        before = counts(session)
        metric_windows(session, TODAY)
        metric_windows(session, TODAY)
        assert counts(session) == before
        assert get_revision(session) == revision
        assert explain_metric(session, volume["id"])["value"] == volume["value"]
        detail = activity_execution(session, ids[-1])
        assert detail["rpe"]["effective"] == 5
        assert detail["rpe"]["srpe_load_au"] == 300
        assert detail["delayed_response"] is None
        assert set(detail) == {
            "activity",
            "planned",
            "completion",
            "laps",
            "watch_steps",
            "planned_actual",
            "intervals",
            "intensity",
            "aerobic",
            "rpe",
            "symptoms",
            "delayed_response",
        }
        nights = recovery_nights(session, TODAY - timedelta(days=2), TODAY)
        assert len(nights["nights"]) == 3
        assert all(night["hrv"]["value"] is None for night in nights["nights"])


def test_source_refresh_history_and_rollback(db, tmp_path):
    ids = seed(db, tmp_path)
    with db() as session:
        session.info["metrics_now"] = NOW
        materialize(session)
        before = get_revision(session)
        old = current(session, "run_volume_frequency", f"w7:{TODAY}")
        old_id = old.id
        row = session.get(Activity, ids[0])
        row.timer_s = 1900
        bump_data_revision(session)
        bump_data_revision(session)
        session.commit()
        assert get_revision(session) == before + 1
        fresh = current(session, "run_volume_frequency", f"w7:{TODAY}")
        assert fresh.value["timer_duration_s"] == 10000
        assert fresh.id != old_id
        assert explain_metric(session, old_id)["value"]["timer_duration_s"] == 9900
        baseline = counts(session)
        row.timer_s = 9000
        session.flush()
        session.rollback()
        assert session.get(Activity, ids[0]).timer_s == 1900
        assert counts(session) == baseline
        assert not session.info.get("metrics_scopes")
        assert get_revision(session) == before + 1
        session.get(Activity, ids[0]).timer_s = 1800
        session.commit()
        assert get_revision(session) == before + 2
        assert current(session, "run_volume_frequency", f"w7:{TODAY}").value["timer_duration_s"] == 9900


def test_revision_bump_once_per_transaction_with_savepoint_rollback(db):
    with db() as session:
        initial = get_revision(session)
        assert bump_data_revision(session) == initial + 1
        assert bump_data_revision(session) == initial + 1
        session.commit()
        before = get_revision(session)
        assert before == initial + 1
        savepoint = session.begin_nested()
        assert bump_data_revision(session) == before + 1
        savepoint.rollback()
        assert get_revision(session) == before
        assert bump_data_revision(session) == before + 1
        savepoint = session.begin_nested()
        assert bump_data_revision(session) == before + 1
        savepoint.rollback()
        assert bump_data_revision(session) == before + 1
        session.commit()
        assert bump_data_revision(session) == before + 2
        session.rollback()
        assert get_revision(session) == before + 1
        assert bump_data_revision(session) == before + 2
        session.commit()


@pytest.mark.parametrize("method", ["explicit", "auto_same_day", "confirmed_move"])
def test_every_link_writeback(db, tmp_path, method):
    from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion

    ids = seed(db, tmp_path)
    uid = uuid.uuid4()
    with db() as session:
        session.info["metrics_now"] = NOW
        session.get(AppState, 1).calendar_head_version = 1
        session.add(CalendarVersion(number=1, kind="bootstrap", actor="system"))
        session.flush()
        session.add(
            CalendarSessionRevision(
                session_uid=uid,
                revision=1,
                calendar_version_number=1,
                local_date=TODAY,
                kind="run",
                intent="Test run",
                planned_duration_s=3000,
                certainty="committed",
            )
        )
        completion = SessionCompletion(
            session_uid=uid,
            activity_id=ids[-1],
            status="unknown",
            match_method=method,
            modification_reason="symptom_onset",
            version=1,
            input_version=1,
            updated_at=NOW,
        )
        session.add(completion)
        session.get(Activity, ids[-1]).timer_s = 2820
        session.commit()
        expected = "moved" if method == "confirmed_move" else "completed_modified"
        assert completion.status == expected
        output = activity_execution(session, ids[-1])
        assert output["planned_actual"]["value"]["overall_status"] == expected
        assert output["completion"]["status"] == expected
        assert completion.match_method == method
        version = completion.version
        baseline = counts(session)
        activity_execution(session, ids[-1])
        assert completion.version == version
        assert counts(session) == baseline
        completion.modification_reason = None
        completion.input_version += 1
        session.get(Activity, ids[-1]).timer_s = 1500
        session.commit()
        # A shorter unstructured run is modified; partial requires unfinished prescribed steps.
        assert completion.status == ("moved" if method == "confirmed_move" else "completed_modified")
        assert completion.match_method == method


def test_derived_failure_rolls_back_source_and_revision(db, tmp_path, monkeypatch):
    ids = seed(db, tmp_path)
    with db() as session:
        session.info["metrics_now"] = NOW
        metric_windows(session, TODAY)
        before = counts(session)
        revision = get_revision(session)
        session.get(Activity, ids[0]).timer_s = 9999

        def fail_refresh(*args):
            raise RuntimeError("synthetic calculation failure")

        monkeypatch.setattr(derived, "refresh_scopes", fail_refresh)
        with pytest.raises(RuntimeError, match="synthetic calculation"):
            session.commit()
        session.rollback()
        assert session.get(Activity, ids[0]).timer_s == 1800
        assert counts(session) == before
        assert get_revision(session) == revision
        assert not session.info.get("metrics_running")
        assert not session.info.get("metrics_scopes")


def test_trace_and_anchor_history(db, tmp_path):
    from app.fit_models import ActivityStream
    from app.metrics.anchors import create_anchor

    ids = seed(db, tmp_path)
    with db() as session:
        session.info["metrics_now"] = NOW
        for kind, value in [("hr_aerobic_upper", 150), ("hr_threshold_lower", 170)]:
            create_anchor(
                session,
                {
                    "kind": kind,
                    "value_low": value,
                    "unit": "bpm",
                    "protocol": "manual",
                    "confidence": "high",
                    "calibrated_at": datetime(2025, 1, 1, tzinfo=UTC),
                    "valid_from": date(2025, 1, 1),
                },
            )
        stream = ActivityStream(
            activity_id=ids[-1],
            t_s=list(range(3601)),
            hr_bpm=[140] * 3000 + [165] * 601,
            speed_mps=[None] * 3601,
            distance_m=[None] * 3601,
            altitude_m=[None] * 3601,
            cadence=[None] * 3601,
            timer_on=[[0, 3600]],
            sample_count=3601,
            max_gap_s=1,
            quality_flags=[],
        )
        session.add(stream)
        session.commit()
        metric = activity_execution(session, ids[-1])["intensity"]
        assert metric["value"]["hr"]["easy_s"] == 3000
        assert metric["value"]["hr"]["moderate_s"] == 600
        assert metric["value"]["hr"]["high_s"] == 0
        assert metric["value"]["hr"]["coverage"] == 1
        assert metric["value"]["speed"]["status"] == "not_assessable"
        assert metric["value"]["speed"]["easy_s"] is None
        old_id = metric["id"]
        stream.hr_bpm = [140] * 3601
        session.commit()
        fresh = activity_execution(session, ids[-1])["intensity"]
        assert fresh["id"] != old_id
        assert fresh["value"]["hr"]["easy_s"] == 3600
        assert explain_metric(session, old_id)["value"]["hr"]["moderate_s"] == 600
        count = counts(session)
        activity_execution(session, ids[-1])
        assert counts(session) == count


def test_recovery_correction_preserves_prior_explanation(db, tmp_path):
    from app.models import RecoveryObservation, SourceRecord

    ids = seed(db, tmp_path)
    with db() as session:
        session.info["metrics_now"] = NOW
        account = session.get(Activity, ids[0]).source_account_id
        source = session.scalar(select(SourceRecord).where(SourceRecord.source_account_id == account))
        source.fields = {**source.fields, "device_generation": "synthetic"}
        observations = []
        for index in range(31):
            row = RecoveryObservation(
                source_account_id=account,
                source_record_id=source.id,
                metric="hrv",
                source_date=TODAY - timedelta(days=30 - index),
                time_semantics="night",
                value=(60 if index < 15 else 70) if index < 30 else 50,
                unit="ms",
                statistic="nightly_mean",
                source_revision=str(index),
            )
            observations.append(row)
            session.add(row)
        session.commit()
        old = current(session, "recovery_multisignal_summary", f"night:{TODAY}")
        assert old.value["hrv"]["z"] == -2.27
        assert old.value["hrv"]["baseline_state"] == "established"
        old_id = old.id
        observations[0].value = 70
        observations[0].source_revision = "corrected"
        session.commit()
        fresh = current(session, "recovery_multisignal_summary", f"night:{TODAY}")
        assert fresh.id != old_id
        assert explain_metric(session, old_id)["value"]["hrv"]["z"] == -2.27
        assert fresh.value["hrv"]["baseline_median"] == pytest.approx(4.248, abs=0.001)


def test_old_new_activity_date_invalidation(db, tmp_path):
    from app.models import ActivityAnnotation

    ids = seed(db, tmp_path)
    with db() as session:
        session.info["metrics_now"] = NOW
        metric_windows(session, TODAY)
        activity = session.get(Activity, ids[0])
        activity.start_at -= timedelta(days=10)
        activity.end_at -= timedelta(days=10)
        activity.local_date -= timedelta(days=10)
        session.commit()
        assert current(session, "run_volume_frequency", f"w7:{TODAY}").value["run_count"] == 3
        session.add(ActivityAnnotation(activity_id=ids[-1], version=1, excluded=True))
        session.commit()
        assert current(session, "run_volume_frequency", f"w7:{TODAY}").value["run_count"] == 2
        assert current(session, "intensity_time_distribution", str(ids[-1])).status == "not_applicable"


def test_serialized_writers_keep_both_changes(db, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy.orm import Session

    ids = seed(db, tmp_path)
    bound = db.kw["bind"]
    schema = bound.scalar(text("SELECT current_schema()"))
    bound.commit()
    waiting = Event()

    def second_writer():
        with bound.engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            connection.commit()
            with Session(bind=connection, autoflush=False, expire_on_commit=False) as second:
                second.info["metrics_now"] = NOW
                waiting.set()
                second.execute(text("SELECT pg_advisory_xact_lock(71382413)"))
                second.get(Activity, ids[1]).timer_s += 20
                second.commit()

    with db() as first, ThreadPoolExecutor(max_workers=1) as pool:
        first.info["metrics_now"] = NOW
        first.execute(text("SELECT pg_advisory_xact_lock(71382413)"))
        revision = get_revision(first)
        first.get(Activity, ids[0]).timer_s += 100
        future = pool.submit(second_writer)
        assert waiting.wait(5)
        first.commit()
        future.result(timeout=20)
    with db() as session:
        assert get_revision(session) == revision + 2
        assert session.get(Activity, ids[0]).timer_s == 1900
        assert session.get(Activity, ids[1]).timer_s == 2420
        assert current(session, "run_volume_frequency", f"w7:{TODAY}").value["timer_duration_s"] == 10020


class FixedFactory:
    def __init__(self, db):
        self.db = db

    def __call__(self):
        session = self.db()
        session.info["metrics_now"] = NOW
        return session

    def begin(self):
        from contextlib import contextmanager

        @contextmanager
        def transaction():
            with self() as session:
                with session.begin():
                    yield session

        return transaction()


def test_cli_recompute_and_preview(db, tmp_path, monkeypatch, capsys):
    import json
    import sys

    from app import cli
    from app.services import strong_import

    seed(db, tmp_path)
    monkeypatch.setattr(cli, "SessionLocal", FixedFactory(db))
    args = [
        "cli",
        "metrics-recompute",
        "--since",
        str(TODAY),
        "--until",
        str(TODAY),
        "--metric",
        "run_volume_frequency",
    ]
    monkeypatch.setattr(sys, "argv", args)
    assert cli.main() == 0
    first = json.loads(capsys.readouterr().out)
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out) == first
    monkeypatch.setattr(sys, "argv", ["cli", "metrics-recompute", "--metric", "unknown"])
    assert cli.main() == 2
    capsys.readouterr()
    calls = []

    def preview(session, private_dir, path, *, apply):
        calls.append(apply)
        return {"status": "preview"}

    monkeypatch.setattr(strong_import, "import_strong_csv", preview)
    monkeypatch.setattr(sys, "argv", ["cli", "strong-import", str(tmp_path / "synthetic.csv")])
    assert cli.main() == 0
    assert calls == [False]


def test_calendar_edit_cost_does_not_grow_with_history(db, tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="going_bananas.metrics")
    seed(db, tmp_path)
    uid = uuid.uuid4()
    with db() as session:
        session.info["metrics_now"] = NOW
        _move_plan(session, uid, 1, TODAY + timedelta(days=1))
        baseline = _statements(session, lambda: _move_plan(session, uid, 2, TODAY + timedelta(days=2)))
        old_runs = [
            {
                "activityId": 5000 + n,
                "startTimeGMT": (datetime(2024, 6, 1, 12, tzinfo=UTC) + timedelta(days=3 * n)).isoformat(),
                "activityType": {"typeKey": "running"},
                "duration": 1800,
                "distance": 5000,
            }
            for n in range(12)
        ]
        import_activity_page(session, tmp_path, old_runs, account_scope="synthetic-metrics", source_kind="demo_fixture")
        session.commit()
        grown = _statements(session, lambda: _move_plan(session, uid, 3, TODAY + timedelta(days=3)))
    assert baseline > 0
    assert grown <= baseline + 10
    assert any(record.getMessage().startswith("refresh ") for record in caplog.records)


def test_load_runs_statement_count_does_not_grow_with_runs(db, tmp_path):
    seed(db, tmp_path)
    window = (date(2024, 1, 1), TODAY + timedelta(days=1))
    with db() as session:
        session.info["metrics_now"] = NOW
        before = _statements(session, lambda: engine.load_runs(session, *window))
    with db() as session:
        session.info["metrics_now"] = NOW
        more = [
            {
                "activityId": 6000 + n,
                "startTimeGMT": (datetime(2024, 9, 1, 12, tzinfo=UTC) + timedelta(days=5 * n)).isoformat(),
                "activityType": {"typeKey": "running"},
                "duration": 1800,
                "distance": 5000,
            }
            for n in range(8)
        ]
        import_activity_page(session, tmp_path, more, account_scope="synthetic-metrics", source_kind="demo_fixture")
        session.commit()
    with db() as session:
        session.info["metrics_now"] = NOW
        facts = engine.load_runs(session, *window)
        after = _statements(session, lambda: engine.load_runs(session, *window))
    assert len(facts) == 12
    assert after == before


def test_planning_only_writes_bump_revision_without_refresh(db, tmp_path, monkeypatch):
    from app.planning_models import Goal

    seed(db, tmp_path)
    calls: list[set[str]] = []
    real = derived.refresh_scopes

    def spy(session, scopes):
        calls.append(set(scopes))
        return real(session, scopes)

    monkeypatch.setattr(derived, "refresh_scopes", spy)
    with db() as session:
        session.info["metrics_now"] = NOW
        revision = get_revision(session)
        session.add(Goal(text="Synthetic goal", horizon="season", priority=1, status="active"))
        session.commit()
        session.add(
            ProfileVersion(
                version=2, effective_at=NOW, timezone="America/New_York", facts={}, preferences={}, unknowns=[]
            )
        )
        session.commit()
        assert calls == []
        assert get_revision(session) == revision + 2
        changed_profile = ProfileVersion(
            version=3, effective_at=NOW, timezone="Europe/London", facts={}, preferences={}, unknowns=[]
        )
        session.add(changed_profile)
        session.commit()
        assert calls == [{"timezone"}]

        session.delete(changed_profile)
        session.commit()
        assert calls == [{"timezone"}, {"timezone"}]
        assert get_revision(session) == revision + 4


def test_spacing_windows_refresh_only_near_changed_dates(db, tmp_path, monkeypatch):
    from dataclasses import replace

    seed(db, tmp_path)
    uid = uuid.uuid4()
    near, far = TODAY - timedelta(days=20), TODAY - timedelta(days=80)
    with db() as session:
        session.info["metrics_now"] = NOW
        _move_plan(session, uid, 1, near)
        refresh.ensure_windows(session, near)
        refresh.ensure_windows(session, far)
        session.commit()
        assert set(engine.current_results(session, "hard_session_spacing", [f"w14:{near}", f"w14:{far}"])) == {
            f"w14:{near}",
            f"w14:{far}",
        }
        engine.metric_modules()
        original = engine.REGISTRY["hard_session_spacing"]
        computed: list[str] = []

        def spy(spy_session, key):
            computed.append(key)
            return original.compute(spy_session, key)

        monkeypatch.setitem(engine.REGISTRY, "hard_session_spacing", replace(original, compute=spy))
        _move_plan(session, uid, 2, TODAY - timedelta(days=17))
    assert f"w14:{near}" in computed
    assert f"w14:{far}" not in computed


def test_deleting_completion_refreshes_its_plan(db, tmp_path):
    from app.calendar_models import SessionCompletion

    seed(db, tmp_path)
    uid = uuid.uuid4()
    with db() as session:
        session.info["metrics_now"] = NOW
        _move_plan(session, uid, 1, TODAY + timedelta(days=1))
        completion = SessionCompletion(session_uid=uid, status="skipped", match_method="user_marked", updated_at=NOW)
        session.add(completion)
        session.commit()
        revision = get_revision(session)
        skipped = current(session, "planned_actual_session", str(uid))
        assert skipped.value["overall_status"] == "skipped"

        session.delete(completion)
        session.commit()

        assert get_revision(session) == revision + 1
        recomputed = current(session, "planned_actual_session", str(uid))
        assert recomputed.value["overall_status"] == "unknown"
        assert recomputed.id != skipped.id


def test_planned_actual_compute_is_pure_and_refresh_writes_status(db, tmp_path):
    from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion

    ids = seed(db, tmp_path)
    uid = uuid.uuid4()
    with db() as session:
        session.info["metrics_now"] = NOW
        session.get(AppState, 1).calendar_head_version = 1
        session.add(CalendarVersion(number=1, kind="bootstrap", actor="system"))
        session.flush()
        session.add(
            CalendarSessionRevision(
                session_uid=uid,
                revision=1,
                calendar_version_number=1,
                local_date=TODAY,
                kind="run",
                intent="Test run",
                planned_duration_s=3000,
                certainty="committed",
            )
        )
        session.add(
            SessionCompletion(
                session_uid=uid,
                activity_id=ids[-1],
                status="unknown",
                match_method="explicit",
                modification_reason="symptom_onset",
                version=1,
                input_version=1,
                updated_at=NOW,
            )
        )
        session.commit()
        session.execute(
            text("UPDATE session_completions SET status = 'unknown' WHERE session_uid = :uid"), {"uid": uid}
        )
        session.commit()
        session.expire_all()
        completion = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == uid))
        version, revision = completion.version, get_revision(session)
        engine.metric_modules()
        (result,) = engine.REGISTRY["planned_actual_session"].compute(session, str(uid))
        assert result.value["overall_status"] == "completed_modified"
        assert completion.status == "unknown"
        assert not session.dirty
        refresh.assess_completion(session, uid)
        assert completion.status == "completed_modified"
        assert completion.version == version + 1
        assert get_revision(session) == revision + 1


def test_read_results_previews_without_writing_then_serves_stored(db, tmp_path):
    seed(db, tmp_path)
    as_of = TODAY - timedelta(days=1)
    key = f"w7:{as_of}"
    metric = "run_volume_frequency"
    with db() as session:
        session.info["metrics_now"] = NOW
        before = counts(session)
        preview = engine.read_results(session, metric, [key])[key]
        assert preview["id"] is None and preview["is_current"] is False
        assert preview["value"]["run_count"] == 3
        srpe_key = f"{key}:run"
        srpe = engine.read_results(session, "session_rpe_load", [srpe_key])[srpe_key]
        assert srpe is not None and srpe["subject_key"] == srpe_key
        assert srpe["id"] is None
        assert counts(session) == before and not session.new and not session.dirty
        refresh.ensure_windows(session, as_of)
        session.commit()
        stored = engine.read_results(session, metric, [key])[key]
        assert stored["id"] is not None and set(stored) == set(preview)
        assert (stored["value"], stored["dependency_hash"]) == (preview["value"], preview["dependency_hash"])

        session.execute(
            text("UPDATE metric_results SET config_hash = :stale WHERE id = :id"),
            {"stale": "0" * 64, "id": stored["id"]},
        )
        session.commit()
        session.expire_all()
        assert engine.read_results(session, metric, [key])[key] == preview

        session.execute(
            text("UPDATE metric_results SET method_version = 'obsolete', config_hash = :config WHERE id = :id"),
            {"id": stored["id"], "config": stored["config_hash"]},
        )
        session.commit()
        session.expire_all()
        assert engine.read_results(session, metric, [key])[key] == preview


def test_metric_gets_write_nothing(db, tmp_path):
    ids = seed(db, tmp_path)
    with db() as session:
        session.info["metrics_now"] = NOW
        materialize(session)
        stale = current(session, "run_volume_frequency", f"w7:{TODAY}")
        session.execute(
            text("UPDATE metric_results SET config_hash = :stale WHERE id = :id"), {"stale": "0" * 64, "id": stale.id}
        )
        session.commit()
        session.expire_all()
        session.execute(text("SET TRANSACTION READ ONLY"))
        transaction = session.get_transaction()
        before, revision = counts(session), get_revision(session)
        windows = metric_windows(session, TODAY)["windows"]
        activity_execution(session, ids[-1])
        recovery_nights(session, TODAY - timedelta(days=2), TODAY)
        long_run_history(session, TODAY - timedelta(days=13), TODAY)
        assert session.get_transaction() is transaction
        assert counts(session) == before
        assert get_revision(session) == revision
        assert not session.dirty and not session.new
        assert windows[0]["volume"]["id"] is None
        assert windows[0]["volume"]["value"]["run_count"] == 4
        assert windows[1]["volume"]["id"] is not None


def test_metrics_refresh_today_cli(db, tmp_path, monkeypatch, capsys):
    import json
    import sys

    from app import cli

    seed(db, tmp_path)
    monkeypatch.setattr(cli, "SessionLocal", FixedFactory(db))
    monkeypatch.setattr(sys, "argv", ["cli", "metrics-refresh-today"])
    assert cli.main() == 0
    first = json.loads(capsys.readouterr().out)
    assert first["as_of"] == str(TODAY) and set(first) == {"as_of", "new_results", "ms"}
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["new_results"] == 0
    with db() as session:
        session.execute(
            text(
                "UPDATE metric_results SET config_hash = :stale WHERE is_current "
                "AND metric_id = 'run_volume_frequency' AND subject_key = :key"
            ),
            {"stale": "0" * 64, "key": f"w7:{TODAY}"},
        )
        session.commit()
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["new_results"] > 0


def test_historical_completion_relink_refreshes_adjacent_plan_candidates(db, tmp_path):
    from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion

    seed(db, tmp_path)
    first_day, second_day = TODAY - timedelta(days=35), TODAY - timedelta(days=24)
    first_plan, second_plan, claimant = (uuid.uuid4() for _ in range(3))
    with db() as session:
        session.info["metrics_now"] = NOW
        session.add(CalendarVersion(number=1, kind="bootstrap", actor="system"))
        session.flush()
        session.get(AppState, 1).calendar_head_version = 1
        for uid, day in (
            (first_plan, first_day + timedelta(days=1)),
            (second_plan, second_day + timedelta(days=1)),
            (claimant, first_day - timedelta(days=3)),
        ):
            session.add(
                CalendarSessionRevision(
                    session_uid=uid,
                    revision=1,
                    calendar_version_number=1,
                    local_date=day,
                    kind="run",
                    intent="Historical plan",
                    planned_duration_s=1800,
                    certainty="committed",
                )
            )
        session.commit()

        records = []
        for index, day in enumerate((first_day, second_day)):
            stamp = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=12)
            records.append(
                {
                    "activityId": 7000 + index,
                    "startTimeGMT": stamp.isoformat(),
                    "activityType": {"typeKey": "running"},
                    "duration": 1800,
                    "distance": 5000,
                }
            )
        import_activity_page(session, tmp_path, records, account_scope="synthetic-metrics", source_kind="demo_fixture")
        session.commit()
        first_run, second_run = session.scalars(
            select(Activity.id).where(Activity.start_at < NOW - timedelta(days=20)).order_by(Activity.start_at)
        ).all()

        def candidates(uid):
            row = current(session, "planned_actual_session", str(uid))
            assert row is not None
            return row.value["candidate_activity_ids"]

        for uid in (first_plan, second_plan):
            refresh.assess_completion(session, uid)
        session.commit()
        assert candidates(first_plan) == [str(first_run)]
        assert candidates(second_plan) == [str(second_run)]

        completion = SessionCompletion(
            session_uid=claimant, activity_id=first_run, status="unknown", match_method="confirmed_move", updated_at=NOW
        )
        session.add(completion)
        session.commit()
        assert candidates(first_plan) == []
        assert candidates(second_plan) == [str(second_run)]

        completion.activity_id = second_run
        completion.input_version += 1
        session.commit()
        assert candidates(first_plan) == [str(first_run)]
        assert candidates(second_plan) == []

        session.delete(completion)
        session.commit()
        assert candidates(first_plan) == [str(first_run)]
        assert candidates(second_plan) == [str(second_run)]
