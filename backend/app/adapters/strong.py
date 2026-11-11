"""Strict, source-faithful reader for Strong's set-per-row CSV export."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

COLUMNS = ("Date", "Workout Name", "Duration", "Exercise Name", "Set Order", "Weight", "Reps", "Distance", "Seconds", "RPE")
ADAPTER_VERSION = "strong-csv-v1"
_DURATION = re.compile(r"(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?\s*$")


class StrongCSVError(ValueError):
    """Safe reason code; never contains private input."""


@dataclass(frozen=True)
class StrongWorkout:
    source_identity: str
    payload_hash: str
    local_start: str
    local_date: str
    workout_name: str
    duration_s: int | None
    sets: list[dict[str, str]]
    row_count: int


def _duration_seconds(value: str) -> int | None:
    if not value.strip():
        return None
    match = _DURATION.fullmatch(value.strip())
    if match is None or not any(part is not None for part in match.groups()):
        raise StrongCSVError("invalid_duration")
    seconds = sum(int(part or 0) * factor for part, factor in zip(match.groups(), (3600, 60, 1), strict=True))
    if seconds > 24 * 3600:
        # Strong's timer can run for days. Preserve its original text in the
        # set rows, but do not treat that value as workout duration.
        return None
    return seconds


def scan_strong_csv(path: Path, *, max_bytes: int = 100_000_000, max_rows: int = 250_000) -> tuple[list[StrongWorkout], str, int]:
    """Read the entire CSV before any write; group sets by exact workout timestamp.

    Strong supplies no timezone, weight unit, or stable workout ID. These remain
    unknown. The timestamp + workout name is a source-local identity.
    """
    size = path.stat().st_size
    if size > max_bytes:
        raise StrongCSVError("csv_too_large")
    with path.open("rb") as binary:
        digest = hashlib.file_digest(binary, "sha256").hexdigest()
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    durations: dict[tuple[str, str], int | None] = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise StrongCSVError("unsupported_columns")
        for row_number, row in enumerate(reader, 1):
            if row_number > max_rows:
                raise StrongCSVError("too_many_rows")
            if None in row or any(value is None for value in row.values()):
                raise StrongCSVError("malformed_row")
            try:
                parsed_start = datetime.strptime(row["Date"], "%Y-%m-%d %H:%M:%S")
            except ValueError as exc:
                raise StrongCSVError("invalid_date") from exc
            if not row["Workout Name"].strip() or not row["Exercise Name"].strip():
                raise StrongCSVError("missing_name")
            for field in ("Weight", "Reps", "Distance", "Seconds", "RPE"):
                value = row[field].strip()
                if value:
                    try:
                        number = float(value)
                    except ValueError as exc:
                        raise StrongCSVError("invalid_number") from exc
                    if not 0 <= number < 1_000_000 or number != number:
                        raise StrongCSVError("invalid_number")
            if row["Set Order"] not in {"W", "F", *map(str, range(1, 100))}:
                raise StrongCSVError("invalid_set_order")
            key = (parsed_start.strftime("%Y-%m-%d %H:%M:%S"), row["Workout Name"])
            duration = _duration_seconds(row["Duration"])
            if key in durations and durations[key] != duration:
                raise StrongCSVError("inconsistent_duration")
            durations[key] = duration
            groups.setdefault(key, []).append({field: row[field] for field in COLUMNS})
    if not groups:
        raise StrongCSVError("empty_csv")
    workouts = []
    for (stamp, name), sets in sorted(groups.items()):
        # Preserve row order and exact text, including the source's weight convention.
        encoded = json.dumps(sets, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        identity = hashlib.sha256(json.dumps([stamp, name], ensure_ascii=False).encode("utf-8")).hexdigest()
        workouts.append(StrongWorkout(identity, hashlib.sha256(encoded).hexdigest(), stamp, stamp[:10],
                                      name, durations[(stamp, name)], sets, len(sets)))
    return workouts, digest, size
