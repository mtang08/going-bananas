"""Measure full PostgreSQL calendar completion requests with ten stored window dates."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import wraps
from statistics import median
from time import perf_counter

from sqlalchemy import delete, select

from app.api import calendar as calendar_api
from app.calendar_models import CalendarSessionRevision, CalendarVersion, SessionCompletion
from app.db import get_session
from app.fit_models import ActivityStream
from app.metric_models import MetricResult, Prompt
from app.metrics import engine, refresh, spacing
from app.models import Activity, CoverageInterval
from app.planning_models import StrengthRoutineSlot
from app.read.calendar import latest_revisions
from app.services import calendar, derived

TODAY = date(2034, 9, 27)
NOW = datetime(2034, 9, 27, 18, tzinfo=UTC)
RUN_DAY = TODAY - timedelta(days=2)
STRENGTH_DAY = TODAY - timedelta(days=1)
AS_OFS = [TODAY - timedelta(days=offset) for offset in range(10)]
PLAN_METRIC = "planned_actual_session"
SPACING = "hard_session_spacing"
VOLUME = "run_volume_frequency"
HEADERS = {"X-Local-Request": "1", "Origin": "http://testserver"}


def _run(day):
    started = datetime(day.year, day.month, day.day, 13, tzinfo=UTC)
    return Activity(
        start_at=started,
        original_start=started.isoformat(),
        end_at=started + timedelta(minutes=30),
        local_date=day,
        sport="running",
        timer_s=1800,
        distance_m=5000,
        canonical_revision=1,
        resolution_state="resolved",
        field_provenance={},
    )


def _record_work(monkeypatch):
    calls = []
    engine.metric_modules()

    def instrument(metric):
        @wraps(metric.compute)
        def compute(session, key):
            calls.append((metric.metric_id, key))
            return metric.compute(session, key)

        return replace(metric, compute=compute)

    for metric_id, metric in engine.REGISTRY.items():
        if metric_id != SPACING:
            monkeypatch.setitem(engine.REGISTRY, metric_id, instrument(metric))

    spacing_outcome = spacing.spacing_outcome

    @wraps(spacing_outcome)
    def instrument_spacing(exposures, as_of, tz):
        calls.append((SPACING, f"w14:{as_of}"))
        return spacing_outcome(exposures, as_of, tz)

    monkeypatch.setattr(spacing, "spacing_outcome", instrument_spacing)
    return calls


def _current(session, metric, key):
    result = engine.current_results(session, metric, [key]).get(key)
    assert result is not None, (metric, key)
    return result


def _prompt(session, uid):
    prompt = session.scalar(select(Prompt).where(Prompt.session_uid == uid, Prompt.kind == "missing_activity"))
    assert prompt is not None
    return prompt.status


def test_manual_completion_refresh_benchmark(api_client, session_factory, profile_factory, calendar_state, monkeypatch):
    def api_session():
        with session_factory(expire_on_commit=False) as session:
            session.info["metrics_now"] = NOW
            yield session

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(calendar_api, "datetime", FrozenDateTime)
    monkeypatch.setattr(calendar, "calendar_today", lambda session, now=None: TODAY)
    client = api_client(calendar_api.router, overrides={get_session: api_session})
    with monkeypatch.context() as seed:
        seed.setattr(derived, "REFRESH_ENABLED", False)
        seed.setattr(calendar, "calendar_today", lambda session, now=None: RUN_DAY)
        with session_factory() as session:
            session.info["metrics_now"] = NOW
            for model in (MetricResult, SessionCompletion, CalendarSessionRevision, CalendarVersion):
                session.execute(delete(model))
            calendar_state(session, reset_head=True)
            profile_factory(session, effective_at=NOW - timedelta(days=1))
            slot = StrengthRoutineSlot(label="Benchmark lower body", default_weekday=1, lower_body_cost="moderate")
            session.add(slot)
            recorded = _run(TODAY - timedelta(days=5))
            session.add(recorded)
            session.add(
                CoverageInterval(
                    dataset="activities",
                    start_date=TODAY - timedelta(days=20),
                    end_date=TODAY,
                    status="complete",
                    fully_enumerated=True,
                )
            )
            session.flush()
            ticks = list(range(1800))
            session.add(
                ActivityStream(
                    activity_id=recorded.id,
                    t_s=ticks,
                    hr_bpm=[132 + tick // 180 + (tick // 10) % 3 for tick in ticks],
                    speed_mps=[2.78 + 0.03 * ((tick // 10) % 3 - 1) for tick in ticks],
                    distance_m=[5000 * tick / 1800 for tick in ticks],
                    altitude_m=[105.0 + tick % 180 / 90 for tick in ticks],
                    cadence=[165.0] * len(ticks),
                    timer_on=[[0, 1800]],
                    sample_count=len(ticks),
                    max_gap_s=1,
                )
            )
            result = calendar.apply_edits(
                session,
                0,
                [
                    {
                        "op": "add",
                        "fields": {
                            "local_date": RUN_DAY,
                            "kind": "run",
                            "recipe_id": "REC003",
                            "intent": "Intervals",
                            "planned_duration_s": 1800,
                        },
                    },
                    {
                        "op": "add",
                        "fields": {
                            "local_date": STRENGTH_DAY,
                            "kind": "strength",
                            "strength_slot_id": slot.id,
                            "intent": "Lower body strength",
                            "planned_duration_s": 1800,
                        },
                    },
                ],
                "Synthetic completion benchmark",
            )
            plans = {row.kind: uid for uid, row in latest_revisions(session, result["version"]).items()}
            session.commit()
    with session_factory() as session:
        session.info["metrics_now"] = NOW
        for as_of in AS_OFS:
            refresh.ensure_windows(session, as_of)
        derived.generate_prompts(session, NOW)
        baseline_volume = _current(session, VOLUME, f"w7:{TODAY}").id
        baseline_spacing = _current(session, SPACING, f"w14:{TODAY}").source_refs
        assert _prompt(session, plans["run"]) == "open"
        session.commit()

    calls = _record_work(monkeypatch)
    history_loads = 0
    load_runs = spacing.load_runs

    def track_history_load(*args, **kwargs):
        nonlocal history_loads
        history_loads += 1
        return load_runs(*args, **kwargs)

    monkeypatch.setattr(spacing, "load_runs", track_history_load)
    measurements = {}
    work = {}
    history_work = {}
    checks = []
    for kind, uid in sorted(plans.items()):
        endpoint = f"/api/v1/calendar/completions/{uid}"
        for _ in range(3):
            version = 0
            for operation, status in (("mark", "completed_as_planned"), ("undo", "unknown")):
                calls.clear()
                history_loads = 0
                started = perf_counter()
                response = client.put(endpoint, json={"status": status, "expected_version": version}, headers=HEADERS)
                elapsed = perf_counter() - started
                label = (kind, operation)
                measurements.setdefault(label, []).append(elapsed)
                work.setdefault(label, []).append(Counter(calls))
                history_work.setdefault(label, []).append(history_loads)
                assert response.status_code == 200, response.text
                payload = response.json()["data"]
                if operation == "mark":
                    assert (payload["status"], payload["match_method"], payload["activity_id"]) == (
                        status,
                        "user_marked",
                        None,
                    )
                    version = payload["version"]
                else:
                    assert payload is None
                with session_factory() as session:
                    result = _current(session, PLAN_METRIC, str(uid))
                    spacing_result = _current(session, SPACING, f"w14:{TODAY}")
                    checks.append(
                        (
                            kind,
                            operation,
                            tuple(result.reason_codes),
                            spacing_result.source_refs != baseline_spacing,
                            _current(session, VOLUME, f"w7:{TODAY}").id,
                            _prompt(session, uid) if kind == "run" else None,
                        )
                    )

    for label, times in measurements.items():
        counts_by_metric = Counter()
        for (metric, _), count in work[label][0].items():
            counts_by_metric[metric] += count
        print(
            f"{' '.join(label)}: median PUT {median(times) * 1000:.1f} ms (n={len(times)}); "
            f"first PUT calculations={sum(counts_by_metric.values())} {dict(sorted(counts_by_metric.items()))}; "
            f"spacing history loads per PUT={history_work[label]}"
        )
    for kind, operation, reasons, spacing_changed, volume_id, prompt in checks:
        assert reasons == (("SELF_REPORTED_COMPLETION",) if operation == "mark" else ("NO_ACTIVITY_FOUND",))
        assert spacing_changed == (operation == "mark")
        assert volume_id == baseline_volume
        if kind == "run":
            assert prompt == "expired"

    # A later real recording still replaces a self-report through normal commit-time matching.
    response = client.put(
        f"/api/v1/calendar/completions/{plans['run']}",
        json={"status": "completed_as_planned", "expected_version": 0},
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    with session_factory(expire_on_commit=False) as session:
        session.info["metrics_now"] = NOW
        activity = _run(RUN_DAY)
        session.add(activity)
        session.commit()
        matched = session.scalar(select(SessionCompletion).where(SessionCompletion.session_uid == plans["run"]))
        assert matched is not None
        assert (matched.activity_id, matched.match_method) == (activity.id, "auto_same_day")
        assessed = _current(session, PLAN_METRIC, str(plans["run"]))
        assert assessed.source_refs["activity"]["activity"]["id"] == str(activity.id)
        assert assessed.value["match_method"] == "auto_same_day"
        duration = next(
            component for component in assessed.value["components"] if component["name"] == "duration_ratio"
        )
        assert duration["value"] == 1.0

    for label, samples in work.items():
        kind, _ = label
        expected = Counter([(PLAN_METRIC, str(plans[kind]))] + [(SPACING, f"w14:{day}") for day in AS_OFS])
        assert all(sample == expected for sample in samples)
        assert max(history_work[label]) <= 1


def test_easy_self_report_leaves_reporting_windows_cold(
    api_client, session_factory, profile_factory, calendar_state, monkeypatch
):
    def api_session():
        with session_factory(expire_on_commit=False) as session:
            session.info["metrics_now"] = NOW
            yield session

    with monkeypatch.context() as seed:
        seed.setattr(derived, "REFRESH_ENABLED", False)
        seed.setattr(calendar, "calendar_today", lambda session, now=None: RUN_DAY)
        with session_factory() as session:
            session.info["metrics_now"] = NOW
            for model in (MetricResult, SessionCompletion, CalendarSessionRevision, CalendarVersion):
                session.execute(delete(model))
            calendar_state(session, reset_head=True)
            profile_factory(session, effective_at=NOW - timedelta(days=1))
            session.flush()
            result = calendar.apply_edits(
                session,
                0,
                [
                    {
                        "op": "add",
                        "fields": {
                            "local_date": RUN_DAY,
                            "kind": "run",
                            "recipe_id": "REC001",
                            "intent": "Easy run",
                            "planned_duration_s": 1800,
                        },
                    },
                ],
                "Synthetic easy run",
            )
            uid = next(iter(latest_revisions(session, result["version"])))
            session.commit()

    monkeypatch.setattr(calendar, "calendar_today", lambda session, now=None: TODAY)
    calls = _record_work(monkeypatch)
    client = api_client(calendar_api.router, overrides={get_session: api_session})
    endpoint = f"/api/v1/calendar/completions/{uid}"
    mark = client.put(endpoint, json={"status": "completed_as_planned", "expected_version": 0}, headers=HEADERS)
    assert mark.status_code == 200, mark.text
    assert calls == [(PLAN_METRIC, str(uid))]
    with session_factory() as session:
        assert _current(session, PLAN_METRIC, str(uid)).reason_codes == ["SELF_REPORTED_COMPLETION"]
        assert session.scalar(select(MetricResult.id).where(MetricResult.subject_type == "window").limit(1)) is None

    calls.clear()
    undo = client.put(
        endpoint, json={"status": "unknown", "expected_version": mark.json()["data"]["version"]}, headers=HEADERS
    )
    assert undo.status_code == 200, undo.text
    assert undo.json()["data"] is None
    assert calls == [(PLAN_METRIC, str(uid))]
    with session_factory() as session:
        assert _current(session, PLAN_METRIC, str(uid)).reason_codes == ["AWAITING_SYNC"]
        assert session.scalar(select(MetricResult.id).where(MetricResult.subject_type == "window").limit(1)) is None
