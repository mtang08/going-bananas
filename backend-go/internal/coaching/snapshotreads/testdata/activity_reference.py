"""Build a disposable activity fixture and run the Python snapshot readers against it."""

import os
import re
import sys
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend"))

from app.checkin_models import SessionRpe
from app.metric_models import MetricResult
from app.metrics.engine import REGISTRY, metric_modules
from app.models import Activity, ActivityAnnotation, CoverageInterval
from app.services.coverage import coverage
from app.services.decision_inputs import canonical_json
from app.services.snapshot.inputs import _load_metrics, _load_runs
from app.services.timezone import athlete_tz

url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"]).set(
    drivername="postgresql+psycopg"
)
assert url.database == "garmin_test" and url.host in {"localhost", "127.0.0.1"}
as_of = date(2021, 11, 7)
day = timedelta(days=1)
first = as_of - 120 * day
target_schema = url.query["search_path"]
assert re.fullmatch(r"go_parity_[a-f0-9]{32}", target_schema)
url = url.difference_update_query(["search_path"])
with Session(
    create_engine(url, connect_args={"options": f"-csearch_path={target_schema}"})
) as session:
    schema = session.scalar(text("SELECT current_schema()"))
    assert re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
    zone = athlete_tz(session)
    start = datetime.combine(first, time.min, zone).astimezone(UTC)
    end = datetime.combine(as_of + day, time.min, zone).astimezone(UTC)
    for i, (sport, at) in enumerate(
        [
            ("running", start),
            ("trail_running", end - timedelta(microseconds=1)),
            ("treadmill_running", start),
            ("running", start),
            ("running", start - day),
            ("running", end),
            ("cycling", start),
            ("running", start),
            ("running", start),
        ]
    ):
        session.add(
            Activity(
                id=UUID(int=6100 + i),
                sport=sport,
                start_at=at,
                original_start="fixture",
                local_date=date(2000, 1, 1),
                resolution_state="unresolved" if i == 8 else "resolved",
                timer_s=0 if i == 0 else None,
                distance_m=1000.5,
                workout_rpe=3.5 if i in (0, 2) else None,
            )
        )
    session.flush()
    for i, version, excluded in ((0, 1, True), (0, 2, False), (7, 1, True)):
        session.add(
            ActivityAnnotation(
                activity_id=UUID(int=6100 + i), version=version, excluded=excluded
            )
        )
    for i, source, rpe, at in (
        (0, "manual", 0, start),
        (0, "garmin_fit", 2, start + day),
        (1, "garmin_fit", 4, end),
    ):
        session.add(
            SessionRpe(
                activity_id=UUID(int=6100 + i), source=source, rpe=rpe, collected_at=at
            )
        )
    for dataset, lower, upper, status in [
        ("activities", first - day, first, "complete"),
        ("sleep", as_of, as_of + day, "partial"),
        ("excluded", first - day, first - day, "complete"),
        ("excluded", as_of + day, as_of + day, "complete"),
    ]:
        session.add(
            CoverageInterval(
                dataset=dataset,
                start_date=lower,
                end_date=upper,
                status=status,
                fully_enumerated=status == "complete",
                completed_at=end if status == "complete" else None,
                reason=None if status == "complete" else "synthetic",
            )
        )
    metric_modules()
    rows = [
        (r.metric_id, r.method_version, str(UUID(int=6100)), True)
        for r in REGISTRY.values()
    ]
    base, version, *_ = rows[0]
    rows.extend(
        [
            (base, version, f"night:{first + day}", True),
            (base, version, f"night:{first}", True),
            (base, version, f"w84:{as_of}:run", True),
            (base, version, f"w7:{as_of}:strength", True),
            (base, version, f"w14:{as_of}", True),
            (base, version, f"w14:{as_of + day}", True),
            (base, version, str(UUID(int=6107)), True),
            (base, "old", str(UUID(int=6100)), True),
            (base, version, str(UUID(int=6101)), False),
            ("unknown_metric", "v1", str(UUID(int=6100)), True),
        ]
    )
    for i, (metric, method, key, current) in enumerate(rows):
        session.add(
            MetricResult(
                id=UUID(int=6200 + i),
                metric_id=metric,
                method_version=method,
                subject_key=key,
                subject_type="night"
                if key.startswith("night:")
                else "window"
                if key.startswith("w")
                else "activity",
                window_label=None,
                status="available",
                quality_status="limited",
                value={"measured": 12.5},
                unit="m",
                reason_codes=["fixture"],
                anchor_keys=[],
                quality_flags=[],
                source_refs={"private": "excluded"},
                config_hash="a" * 64,
                dependency_hash="b" * 64,
                calculated_at=end,
                timezone=zone.key,
                is_current=current,
            )
        )
    session.commit()
    runs = _load_runs(session, first, as_of, session.scalars(select(SessionRpe)).all())
    print(
        canonical_json(
            {
                "zone": zone.key,
                "runs": runs,
                "metric_results": _load_metrics(session, as_of, runs),
                "coverage": coverage(session, first, as_of),
            }
        )
    )
