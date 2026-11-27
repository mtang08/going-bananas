"""Capture public sections from the original populated Python snapshot cases."""

import sys
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

backend = Path(__file__).resolve().parents[5] / "backend"
sys.path[:0] = [str(backend), str(backend / "tests/unit")]
import test_snapshot as fixtures
from app.services.decision_inputs import canonical_json
from app.services.snapshot.payload import build_payload

sections = {
    "event",
    "benchmark_history",
    "quality_progression",
    "aerobic_efficiency",
    "weekly_digest",
    "travel",
}
cases = []


def capture(inputs, operation):
    payload = build_payload(inputs, operation)
    # Serialize now; a few Python cases edit their fixture between calls.
    cases.append(
        canonical_json(
            {
                "inputs": asdict(inputs),
                "operation": operation,
                "want": {k: v for k, v in payload.items() if k in sections},
            }
        )
    )
    return payload


fixtures.build_payload = capture
for case in [
    fixtures.test_event_section,
    fixtures.test_block_benchmark_sections,
    fixtures.test_quality_progression_section,
    fixtures.test_aerobic_efficiency_section,
    fixtures.test_weekly_digest_week_view_caps_and_shape,
    fixtures.test_weekly_digest_budget,
    fixtures.test_travel_section_shape_cap_and_operations,
    fixtures.test_travel_section_size_for_eight_round_trips,
]:
    case()
for case in [
    fixtures.test_trip_zone_shift_direction_and_nights,
    fixtures.test_leg_duration_shift_and_night_overlap,
    fixtures.test_provisional_calendar_zones_do_not_imply_night_flight_or_circadian_shift,
]:
    for values in case.pytestmark[0].args[1]:
        case(*(values if isinstance(values, tuple) else (values,)))
# More than four usable points, nonuniform repetition weights, missing HR,
# a linked run on a different day, and four competing group signatures.
sessions, completions, runs, metrics = [], [], [], []
for i in range(10):
    day = fixtures.AS_OF - timedelta(days=10 - i)
    planned = fixtures.session(day, "run", "REC003")
    amount = 202.5 if i < 7 else (300, 400, 500)[i - 7]
    planned["structure"] = [
        {"type": "work", "duration_type": "time", "duration_value": amount}
    ]
    sessions.append(planned)
    if i == 1:
        continue
    aid = f"interval-{i}"
    completions.append(
        {
            "session_uid": planned["session_uid"],
            "activity_id": aid,
            "status": "completed_modified",
        }
    )
    runs.append(
        {
            "activity_id": aid,
            "local_date": day + timedelta(days=2 if i == 4 else 0),
            "sport": "running",
            "timer_s": 600,
            "distance_m": 1800,
            "rpe": None,
            "rpe_source": None,
        }
    )
    reps = [
        {
            "fully_completed": True,
            "speed_status": "available",
            "mean_speed_mps": 3.4,
            "actual_timer_s": 40,
            "hr_median_bpm": None,
        },
        {
            "fully_completed": True,
            "speed_status": "available",
            "mean_speed_mps": 3.9,
            "actual_timer_s": 80,
            "hr_median_bpm": 161,
        },
        {
            "fully_completed": False,
            "speed_status": "missing",
            "mean_speed_mps": None,
            "actual_timer_s": None,
            "hr_median_bpm": None,
        },
    ]
    metrics.append(
        {
            "result_id": aid,
            "metric_id": "work_interval_execution",
            "subject_type": "activity",
            "subject_key": aid,
            "status": "partial",
            "reason_codes": ["LIMITED"],
            "value": {
                "reps": reps,
                "n_planned": 3,
                "n_completed": 3,
                "step_completion_ratio": 1,
                "cv_speed": None,
                "last_first_change_pct": None,
                "target_coverage": 0.5,
            },
        }
    )
source = fixtures.inputs(
    sessions=sessions, completions=completions, runs=runs, metric_results=metrics
)
# Isolate this projection because the synthetic rows carry only progression fields.
from app.services.snapshot.payload import _quality_progression

cases.append(
    canonical_json(
        {
            "inputs": asdict(source),
            "operation": fixtures.ROLLING,
            "want": {
                **{
                    k: v
                    for k, v in build_payload(
                        fixtures.inputs(), fixtures.ROLLING
                    ).items()
                    if k in sections
                },
                "quality_progression": _quality_progression(source, fixtures.ROLLING),
            },
        }
    )
)
print("[" + ",".join(cases) + "]")
