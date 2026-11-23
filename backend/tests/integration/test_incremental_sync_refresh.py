"""Incremental Garmin sync against isolated PostgreSQL with synthetic provider responses."""

from collections import Counter
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import wraps
from time import perf_counter
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.api import sync as sync_api
from app.metric_models import MetricResult, Prompt
from app.metrics import engine, refresh
from app.models import Activity, CoverageInterval
from app.services import derived, sync

TODAY = date(2026, 11, 20)
NOW = datetime(2026, 11, 20, 16, tzinfo=UTC)
VOLUME = "run_volume_frequency"
RECOVERY = "recovery_multisignal_summary"


@pytest.fixture(autouse=True)
def clean_sync_state(db_connection):
    # db_connection first verifies the synthetic database and rolls this cleanup
    # back with the test. Other suites can leave committed import fixtures here.
    db_connection.execute(
        text("""
            TRUNCATE source_accounts, activities, recovery_observations,
                     coverage_intervals, sync_jobs, sync_state, metric_results, prompts,
                     profile_versions, calendar_versions, session_completions,
                     checkins_v2, manual_sessions, strong_workouts, intensity_anchors CASCADE
        """)
    )
    db_connection.execute(text("UPDATE app_state SET calendar_head_version = 0 WHERE id = 1"))


def interval(start, end, dataset="activities"):
    return CoverageInterval(dataset=dataset, start_date=start, end_date=end, status="complete", fully_enumerated=True)


def resting_hr(day, value):
    return {"calendarDate": day.isoformat(), "restingHeartRate": value, "userProfilePK": 17701}


def current(session, metric_id, key):
    row = session.scalar(
        select(MetricResult).where(
            MetricResult.metric_id == metric_id,
            MetricResult.subject_key == key,
            engine.current_result_filter(),
        )
    )
    assert row is not None, (metric_id, key)
    return row


@pytest.fixture
def record_work(monkeypatch):
    def start():
        calls = []
        engine.metric_modules()

        def track(registration):
            @wraps(registration.compute)
            def compute(session, key):
                calls.append((registration.metric_id, key))
                return registration.compute(session, key)

            return replace(registration, compute=compute)

        for metric_id, metric in engine.REGISTRY.items():
            monkeypatch.setitem(engine.REGISTRY, metric_id, track(metric))
        return calls

    return start


@pytest.fixture
def frozen_metrics(monkeypatch):
    monkeypatch.setattr(refresh, "clock", lambda _session: NOW)


def test_one_day_incremental_worker_benchmark(
    api_client, session_factory, db_connection, tmp_path, monkeypatch, record_work, frozen_metrics
):
    day = TODAY - timedelta(days=8)
    with monkeypatch.context() as seed:
        seed.setattr(derived, "REFRESH_ENABLED", False)
        with session_factory() as session:
            for dataset in ("activities", "sleep", "hrv", "resting_hr"):
                session.add(interval(day - timedelta(days=14), day, dataset))
            sync.import_recovery_page(session, tmp_path, "resting_hr", [resting_hr(day, 50)])
            session.commit()
        with session_factory() as session:
            for offset in range(9):
                refresh.ensure_windows(session, day + timedelta(days=offset))
            volume_before = current(session, VOLUME, f"w7:{TODAY}").id
            session.commit()

    class SyntheticGarmin:
        def search_page(self, offset, limit, first, last):
            assert (offset, limit, first, last) == (0, 50, day, day)
            return []

        def fetch_recovery(self, dataset, first, last):
            assert (first, last) == (day, day)
            return [resting_hr(day, 57)] if dataset == "resting_hr" else []

    # Keep worker commits inside the integration fixture's outer rollback transaction.
    lock_connection = SimpleNamespace(execute=db_connection.execute, commit=lambda: None)
    monkeypatch.setattr(sync, "engine", SimpleNamespace(connect=lambda: nullcontext(lock_connection)))
    monkeypatch.setattr(sync, "Session", lambda *, bind, **options: session_factory(**options))
    monkeypatch.setattr(sync, "SessionLocal", session_factory)
    monkeypatch.setattr(sync, "GarminPersonalSource", lambda *_: nullcontext(SyntheticGarmin()))
    monkeypatch.setattr(sync_api, "settings", SimpleNamespace(app_mode="real"))

    calls = record_work()
    refresh_times = []
    refresh_scopes = derived.refresh_scopes

    def time_refresh(session, scopes):
        start = perf_counter()
        try:
            return refresh_scopes(session, scopes)
        finally:
            refresh_times.append(perf_counter() - start)

    monkeypatch.setattr(derived, "refresh_scopes", time_refresh)
    client = api_client(sync_api.router)
    start = perf_counter()
    response = client.post(
        "/api/v1/sync",
        json={"start_date": day.isoformat(), "end_date": day.isoformat()},
        headers={"X-Local-Request": "1"},
    )
    queued = perf_counter()
    assert response.status_code == 202, response.text
    jobs = response.json()["data"]["jobs"]
    assert len(jobs) == 4
    assert {job["status"] for job in jobs} == {"queued"}
    for _ in jobs:
        assert sync.run_one_job(tmp_path, tmp_path / "unused-key", "synthetic-benchmark") == "complete"
    elapsed = perf_counter() - start

    metric_counts = Counter(metric for metric, _ in calls)
    window_count = sum(key.startswith("w") for _, key in calls)
    night_count = sum(key.startswith("night:") for _, key in calls)
    print(
        f"one-day sync: {elapsed:.3f}s end to end ({queued - start:.3f}s to queue); "
        f"{sum(refresh_times):.3f}s over {len(refresh_times)} refresh calls; "
        f"{window_count} window and {night_count} night calculations; "
        f"metrics={dict(sorted(metric_counts.items()))}"
    )
    for job in jobs:
        status = client.get(f"/api/v1/sync/jobs/{job['id']}").json()["data"]
        assert status["status"] == "complete"
        seen = int(job["dataset"] == "resting_hr")
        assert status["counters"]["seen"] == seen
        assert status["counters"]["changed"] == seen
    assert calls
    assert set(metric_counts) == {RECOVERY}
    assert len(calls) == len(set(calls))
    assert window_count == 9
    assert night_count == 9
    with session_factory() as session:
        assert current(session, VOLUME, f"w7:{TODAY}").id == volume_before
        assert current(session, RECOVERY, f"night:{day}").value["resting_hr"]["value"] == 57


def test_coverage_gain_and_loss_with_overlap(session_factory, record_work, frozen_metrics):
    previous_end = TODAY + timedelta(days=7)
    today_key = f"w7:{TODAY}"
    previous_key = f"w7:{previous_end}"
    with session_factory() as session:
        session.add(interval(TODAY - timedelta(days=6), TODAY - timedelta(days=1)))
        session.commit()
        with refresh.refreshing(session):
            refresh.compute_subjects(session, VOLUME, [today_key, previous_key])
        session.commit()
        assert current(session, VOLUME, today_key).status == "missing"
        assert not current(session, VOLUME, previous_key).value["previous"]["coverage_complete"]

        calls = record_work()
        savepoint = session.begin_nested()
        session.add(interval(TODAY, TODAY))
        session.flush()
        savepoint.rollback()
        session.commit()
        assert not calls
        assert current(session, VOLUME, today_key).status == "missing"

        single_day = interval(TODAY, TODAY)
        session.add(single_day)
        session.commit()
        assert current(session, VOLUME, today_key).status == "available"
        assert current(session, VOLUME, previous_key).value["previous"]["coverage_complete"]
        assert (VOLUME, previous_key) in calls

        calls.clear()
        overlap = interval(TODAY - timedelta(days=2), TODAY)
        session.add(overlap)
        session.commit()
        session.delete(single_day)
        session.commit()
        assert not calls
        assert current(session, VOLUME, today_key).source_refs["coverage_complete"]

        overlap.status = "partial"
        session.commit()
        assert current(session, VOLUME, today_key).status == "missing"
        assert not current(session, VOLUME, previous_key).value["previous"]["coverage_complete"]


def test_recovery_refresh_stops_after_last_dependent_historical_summary(
    session_factory, tmp_path, record_work, frozen_metrics, monkeypatch
):
    day = TODAY - timedelta(days=70)
    last_night = day + timedelta(days=60)
    last_summary = day + timedelta(days=66)
    nights = [f"night:{on_date}" for on_date in (day, last_night, last_night + timedelta(days=1))]
    summaries = [f"w7:{on_date}" for on_date in (last_summary, last_summary + timedelta(days=1))]
    with session_factory() as session:
        with monkeypatch.context() as seed:
            seed.setattr(derived, "REFRESH_ENABLED", False)
            sync.import_recovery_page(session, tmp_path, "resting_hr", [resting_hr(day, 50)])
            session.commit()
        with refresh.refreshing(session):
            refresh.compute_subjects(session, RECOVERY, nights + summaries)
            refresh.compute_subjects(session, VOLUME, summaries)
        refresh.ensure_windows(session, TODAY)
        session.commit()
        before = {key: current(session, RECOVERY, key).id for key in nights + summaries}
        volume_before = {key: current(session, VOLUME, key).id for key in summaries}

        calls = record_work()
        sync.import_recovery_page(session, tmp_path, "resting_hr", [resting_hr(day, 57)])
        session.commit()
        assert current(session, RECOVERY, nights[0]).value["resting_hr"]["value"] == 57
        for key in (nights[0], nights[1], summaries[0]):
            assert current(session, RECOVERY, key).id != before[key]
            assert (RECOVERY, key) in calls
        for key in (nights[2], summaries[1]):
            assert current(session, RECOVERY, key).id == before[key]
            assert (RECOVERY, key) not in calls
        assert {key: current(session, VOLUME, key).id for key in summaries} == volume_before
        assert {metric for metric, _ in calls} == {RECOVERY}


@pytest.mark.parametrize("trigger", ["duplicate_coverage", "resting_hr"])
@pytest.mark.parametrize("partial_today", [False, True], ids=["empty-today", "partial-today"])
def test_incremental_commit_materializes_training_windows_on_rollover(
    session_factory, tmp_path, monkeypatch, record_work, frozen_metrics, trigger, partial_today
):
    yesterday = TODAY - timedelta(days=1)
    with session_factory() as session:
        with monkeypatch.context() as seed:
            seed.setattr(derived, "REFRESH_ENABLED", False)
            session.add(interval(yesterday - timedelta(days=6), yesterday))
            sync.import_recovery_page(session, tmp_path, "resting_hr", [resting_hr(yesterday, 50)])
            session.commit()
        refresh.ensure_windows(session, yesterday)
        if partial_today:
            session.info["metrics_filter"] = {"hard_session_spacing", "long_run_exposure", "symptom_response_timeline"}
            refresh.ensure_windows(session, TODAY)
            session.info.pop("metrics_filter")
            current(session, "hard_session_spacing", f"w14:{TODAY}")
        session.commit()
        assert not engine.current_results(session, VOLUME, [f"w7:{TODAY}"])

        calls = record_work()
        if trigger == "duplicate_coverage":
            session.add(interval(yesterday, yesterday))
        else:
            sync.import_recovery_page(session, tmp_path, "resting_hr", [resting_hr(yesterday, 57)])
        session.commit()
        assert (VOLUME, f"w7:{TODAY}") in calls
        assert (VOLUME, f"w7:{yesterday}") not in calls
        assert current(session, VOLUME, f"w7:{TODAY}").status == "missing"


def test_duplicate_activity_coverage_advances_prompt_clock(
    session_factory, tmp_path, monkeypatch, record_work, frozen_metrics
):
    day = TODAY - timedelta(days=2)
    start = NOW - timedelta(days=2)
    with session_factory() as session:
        sync.import_activity_page(
            session,
            tmp_path,
            [
                {
                    "activityId": 17702,
                    "startTimeGMT": start.isoformat(),
                    "activityType": {"typeKey": "running"},
                    "duration": 1800,
                    "distance": 5000,
                }
            ],
            account_scope="synthetic-prompt",
            source_kind="demo_fixture",
        )
        activity = session.scalar(select(Activity).where(Activity.garmin_id == "17702"))
        assert activity is not None
        activity.end_at = start + timedelta(minutes=30)
        session.add(interval(day, day))
        session.commit()
        prompt = session.scalar(select(Prompt).where(Prompt.activity_id == activity.id, Prompt.kind == "rpe"))
        assert prompt is not None and prompt.status == "open"

        calls = record_work()
        monkeypatch.setattr(refresh, "clock", lambda _session: NOW + timedelta(hours=1))
        session.add(interval(day, day))
        session.commit()
        assert prompt.status == "expired"
        assert not calls


def test_only_new_treadmill_runs_wait_for_confirmed_interval_paces(
    api_client, session_factory, db_connection, tmp_path, monkeypatch, frozen_metrics
):
    from app.adapters.garmin.fit import DecodedFit, DecodedLap, DecodedSession, DecodedStream
    from app.fit_models import ActivityLap
    from app.models import SourceRecord
    from app.read.treadmill_intervals import confirmed_lap_paces
    from app.services import fit_ingest, treadmill_review

    records = [
        {
            "activityId": str(index),
            "activityName": "Fixture run",
            "ownerId": 17701,
            "startTimeGMT": NOW.isoformat(),
            "activityType": {"typeKey": sport},
            "distance": 3500,
            "movingDuration": 1100,
            "elapsedDuration": 1200,
        }
        for index, sport in enumerate(("treadmill_running", "running", "track_running", "indoor_running"), 1)
    ]
    decoded = DecodedFit(
        fit_sha256="a" * 64,
        profile_version="test",
        sdk_version="test",
        session=DecodedSession(NOW, "treadmill_running", timer_s=1110, distance_m=2700),
        laps=tuple(
            DecodedLap(index, NOW + timedelta(seconds=index * 120), timer_s=120, avg_speed_mps=3.0)
            for index in range(2)
        ),
        steps=(),
        stream=DecodedStream((), (), (), (), (), (), (), 0, 0, ()),
        message_inventory={},
        device={},
        field_names={},
    )
    downloads = []

    class SyntheticGarmin:
        def search_page(self, offset, limit, first, last):
            return records

        def pages(self, first, last):
            yield 0, records

        def download_activity(self, activity_id):
            downloads.append(activity_id)
            return f"synthetic ZIP {activity_id}".encode()

    lock_connection = SimpleNamespace(execute=db_connection.execute, commit=lambda: None)
    monkeypatch.setattr(sync, "engine", SimpleNamespace(connect=lambda: nullcontext(lock_connection)))
    monkeypatch.setattr(sync, "Session", lambda *, bind, **options: session_factory(**options))
    monkeypatch.setattr(sync, "SessionLocal", session_factory)
    for module in (sync, treadmill_review):
        monkeypatch.setattr(module, "GarminPersonalSource", lambda *_: nullcontext(SyntheticGarmin()))
    for module in (fit_ingest, treadmill_review):
        monkeypatch.setattr(module, "extract_fit", lambda archive: archive.replace(b"ZIP", b"FIT"))
        monkeypatch.setattr(module, "decode_fit", lambda *_: decoded)
    monkeypatch.setattr(sync_api, "settings", SimpleNamespace(app_mode="real", private_dir=tmp_path))
    with session_factory() as session:
        sync.enqueue_sync(session, TODAY, TODAY)
        session.commit()

    assert sync.run_one_job(tmp_path, tmp_path / "unused-key", "auto") == "complete"
    assert downloads == ["2", "3", "4"]
    client = api_client(sync_api.router)
    status_url = "/api/v1/sync/status"
    review_url = "/api/v1/sync/treadmill-review/1"
    assert client.get(status_url).json()["data"]["pending_treadmill_runs"] == [
        {"id": "1", "local_date": TODAY.isoformat()}
    ]
    preview = client.get(review_url)
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert data["distance_m"] == 3500
    assert data["timer_s"] == 1110
    assert [lap["lap_index"] for lap in data["intervals"]] == [0, 1]
    with session_factory() as session:
        assert set(session.scalars(select(Activity.garmin_id))) == {"2", "3", "4"}
        assert session.scalar(select(SourceRecord.id).where(SourceRecord.source_identity == "garmin:1")) is None
        assert len(list((tmp_path / "raw").rglob("*.json"))) == 3
        assert session.scalar(select(CoverageInterval.status)) == "partial"

    changes = [
        {"lap_index": 0, "pace_seconds_per_mile": 500},
        {"lap_index": 1, "pace_seconds_per_mile": 490},
    ]
    assert client.post(review_url, json={"preview_token": "stale", "paces": changes}).status_code == 409
    token = data["preview_token"]
    invalid = [{"lap_index": 3, "pace_seconds_per_mile": 500}]
    assert client.post(review_url, json={"preview_token": token, "paces": invalid}).status_code == 422
    saved = client.post(review_url, json={"preview_token": token, "paces": changes})
    assert saved.status_code == 200, saved.text
    assert downloads == ["2", "3", "4", "1"]
    assert client.get(status_url).json()["data"]["pending_treadmill_runs"] == []
    with session_factory() as session:
        activity = session.scalar(select(Activity).where(Activity.garmin_id == "1"))
        assert activity is not None
        assert str(activity.id) == saved.json()["data"]["activity_id"]
        assert (activity.distance_m, activity.elapsed_s, activity.moving_s, activity.timer_s) == (
            3500,
            1200,
            1100,
            1110,
        )
        laps = list(session.scalars(select(ActivityLap).where(ActivityLap.activity_id == activity.id)))
        assert confirmed_lap_paces(activity, laps) == {0: 500, 1: 490}
        assert [lap.avg_speed_mps for lap in laps] == [3.0, 3.0]
        assert session.scalar(select(CoverageInterval.status)) == "complete"

    # An already confirmed treadmill is a normal replay. A newly pending ID
    # can also be imported normally if Garmin later reclassifies it as track.
    records.append({**records[0], "activityId": "5"})
    with session_factory() as session:
        sync.enqueue_sync(session, TODAY, TODAY)
        session.commit()
    assert sync.run_one_job(tmp_path, tmp_path / "unused-key", "auto") == "complete"
    assert client.get(status_url).json()["data"]["pending_treadmill_runs"] == [
        {"id": "5", "local_date": TODAY.isoformat()}
    ]
    records[-1]["activityType"] = {"typeKey": "track_running"}
    with session_factory() as session:
        sync.enqueue_sync(session, TODAY, TODAY)
        session.commit()
    assert sync.run_one_job(tmp_path, tmp_path / "unused-key", "auto") == "complete"
    assert client.get(status_url).json()["data"]["pending_treadmill_runs"] == []
    with session_factory() as session:
        assert session.scalar(select(Activity.subtype).where(Activity.garmin_id == "5")) == "track_running"
        assert set(session.scalars(select(CoverageInterval.status))) == {"complete"}
