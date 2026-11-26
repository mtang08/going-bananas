"""Compare activity normalization and account-export scanning against Python on synthetic data.

uv run --project backend python scripts/rewrite/check_garmin_activities.py
"""

import argparse
import base64
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "backend-go/internal/garmin/replay"
sys.path.insert(0, str(ROOT / "backend"))
from app.adapters.garmin.export import ExportError, scan_activities
from app.adapters.garmin.normalize import InvalidRecord, parse_activity


def api_cases():
    base = {
        "activityId": 9_007_199_254_740_993,
        "startTimeGMT": "2026-01-01T01:00:00Z",
        "activityType": {"typeKey": "running"},
    }
    for name, changes in {
        "metrics": {
            "movingDuration": 0,
            "elapsedDuration": 637.5,
            "averageHR": 147,
            "averageRunningCadenceInStepsPerMinute": 172,
            "distance": 1609.344,
        },
        "summary_only": {
            "summaryDTO": {"distance": 900.5, "averageHR": 0},
            "movingDuration": 600,
        },
        "naive_gmt": {"startTimeGMT": "2026-11-01 05:55:12.1234"},
        "source_offset": {
            "startTimeGMT": None,
            "start_at": "2026-11-01T01:30:00-04:00",
        },
        "fall_back_key": {
            "activityId": 0,
            "id": "runner-7",
            "activityType": None,
            "activityTypeDTO": {"sportTypeKey": "indoor_running"},
        },
        "null_id": {"activityId": None},
        "multisport": {"activityType": "multi_sport"},
        "unknown_sport": {"activityType": "  Snowshoe  "},
        "missing_sport": {"activityType": {}},
        "missing_time": {"startTimeGMT": None},
        "local_only": {"startTimeGMT": None, "startTimeLocal": "2026-11-01T01:30:00"},
        "unqualified_time": {"startTimeGMT": None, "start_at": "2026-11-01T01:30:00"},
        "invalid_time": {"startTimeGMT": "not-a-date"},
        "negative_distance": {"distance": -1},
        "boolean_hr": {"averageHR": True},
        "string_duration": {"elapsedDuration": "600"},
        "invalid_id": {"activityId": 1.0},
    }.items():
        row = {**base, **changes}
        case = {"name": name, "record": row}
        try:
            a = parse_activity(row, "America/New_York")
            case["provider_id"] = a.provider_id or ""
            case["fields"] = {
                "start_at": a.start_at.isoformat(),
                "original_start": a.source_time,
                "source_timezone": a.timezone_assumption,
                "local_date": a.local_date,
                "sport": a.sport,
                "subtype": a.subtype,
                "distance_m": a.distance_m,
                "elapsed_s": a.elapsed_s,
                "moving_s": a.moving_s,
                "avg_hr_bpm": a.average_hr,
                "cadence_spm": a.average_cadence,
                "source_workout_label": a.workout_label,
                "field_paths": a.field_paths,
            }
        except InvalidRecord as exc:
            case["error"] = exc.code
        yield case


def archive(members):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        for name, body in members:
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            z.writestr(entry, body, compress_type=zipfile.ZIP_DEFLATED)
    return data.getvalue()


def export_cases():
    name = "export/example_summarizedActivities.json"
    row = {
        "activityId": 9_007_199_254_740_993,
        "userProfileId": 17,
        "startTimeGmt": 1_756_000_000_125,
        "activityType": "track_running",
        "distance": 525000,
        "elapsedDuration": 1900000,
        "movingDuration": 1800000,
        "avgHr": 145,
        "avgRunCadence": 82,
    }

    def summary(rows):
        return json.dumps(
            [{"summarizedActivitiesExport": rows}], sort_keys=True
        ).encode()

    for title, members in {
        "converted": [
            (name, summary([row, {**row, "activityId": 8, "distance": None}])),
            ("notes.txt", b"ignored"),
        ],
        "missing_member": [("other.json", b"{}")],
        "invalid_json": [(name, b"(not JSON)")],
        "wrong_schema": [(name, b"{}")],
        "non_record": [(name, summary([17]))],
        "duplicate_id": [(name, summary([row, row]))],
        "mixed_owner": [
            (name, summary([row, {**row, "activityId": 8, "userProfileId": 19}]))
        ],
        "empty": [(name, summary([]))],
        "string_id": [(name, summary([{**row, "activityId": "7"}]))],
        "negative_distance": [(name, summary([{**row, "distance": -1}]))],
        "invalid_start": [(name, summary([{**row, "startTimeGmt": 0}]))],
        "unsafe_path": [(name, summary([row])), ("../notes.txt", b"ignored")],
    }.items():
        data = archive(members)
        case = {"name": title, "archive": base64.b64encode(data).decode()}
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                result = scan_activities(z)
                assert z.testzip() is None
            a = result.activities[0]
            case.update(
                owner=a.owner,
                member_name=a.member_name,
                member_count=result.member_count,
                expanded_bytes=result.expanded_bytes,
                records=[
                    {
                        "record": v.normalized,
                        "original": v.original,
                        "member_sha256": v.member_sha256,
                        "row_index": v.row_index,
                    }
                    for v in result.activities
                ],
                archive_sha256=hashlib.sha256(data).hexdigest(),
            )
        except ExportError as exc:
            case["error"] = str(exc)
        yield case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    golden = PACKAGE / "testdata/activity-normalization.json"
    result = (
        json.dumps(
            {"activities": list(api_cases()), "exports": list(export_cases())},
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    if args.update:
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(result)
    elif golden.read_text() != result:
        raise SystemExit(
            "Python activity reference changed; review before updating fixtures."
        )
    subprocess.run(
        ["go", "test", "-count=1", "-run", "^TestActivityReference$", "."],
        cwd=PACKAGE,
        check=True,
    )


if __name__ == "__main__":
    main()
