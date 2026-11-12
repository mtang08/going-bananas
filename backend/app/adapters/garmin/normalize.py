"""Translate verified Garmin activity summary fields into canonical SI values.

Unknown fields are retained in the immutable raw object, never guessed here.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo


class InvalidRecord(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CanonicalActivity:
    provider_id: str | None
    start_at: datetime
    source_time: str
    local_date: str
    timezone_assumption: str
    sport: str
    subtype: str | None
    distance_m: float | None
    elapsed_s: float | None
    moving_s: float | None
    average_hr: float | None
    average_cadence: float | None
    workout_label: str | None
    field_paths: dict[str, str]
    timer_s: float | None = None


def _number(value: Any, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRecord(f"invalid_{field}")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise InvalidRecord(f"invalid_{field}")
    return result


def _timestamp(record: dict[str, Any], timezone: str) -> tuple[datetime, str, str]:
    # Garmin names the unzoned GMT field explicitly; a local-only timestamp is
    # ambiguous around DST and deliberately cannot be promoted to UTC.
    for key in ("startTimeGMT", "startTimeGmt", "start_at"):
        value = record.get(key)
        if not isinstance(value, str) or not value:
            continue
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidRecord("invalid_start_time") from exc
        if instant.tzinfo is None:
            if key not in {"startTimeGMT", "startTimeGmt"}:
                raise InvalidRecord("ambiguous_start_time")
            instant = instant.replace(tzinfo=UTC)
            return instant, value, "garmin_GMT_field"
        return instant.astimezone(UTC), value, "source_offset"
    if record.get("startTimeLocal") is not None:
        raise InvalidRecord("ambiguous_start_time")
    raise InvalidRecord("missing_start_time")


def _sport(record: dict[str, Any]) -> tuple[str, str | None]:
    raw = record.get("activityType") or record.get("activityTypeDTO")
    if isinstance(raw, dict):
        key = raw.get("typeKey") or raw.get("sportTypeKey")
    else:
        key = raw
    if key is None:
        key = record.get("sport")
    if not isinstance(key, str):
        raise InvalidRecord("missing_sport")
    key = key.strip().lower()
    mapping = {
        "running": "running", "trail_running": "trail_running", "treadmill_running": "treadmill_running",
        "track_running": "running", "indoor_rowing": "rowing", "rowing": "rowing",
        "run": "running", "strength_training": "strength", "strength": "strength",
        "walking": "walking", "walk": "walking", "hiking": "hiking", "hike": "hiking",
        "cycling": "cycling", "indoor_cycling": "cycling", "elliptical": "elliptical",
        "swimming": "swimming", "pool_swimming": "swimming", "open_water_swimming": "swimming",
        "multi_sport": "multisport", "multisport": "multisport",
    }
    return mapping.get(key, "other"), key


def parse_activity(record: dict[str, Any], timezone: str = "America/New_York") -> CanonicalActivity:
    if not isinstance(record, dict):
        raise InvalidRecord("invalid_record_shape")
    try:
        zone = ZoneInfo(timezone)
    except (KeyError, ValueError) as exc:
        raise InvalidRecord("invalid_timezone") from exc
    instant, source_time, assumption = _timestamp(record, timezone)
    sport, subtype = _sport(record)
    summary = record.get("summaryDTO")
    data = summary if isinstance(summary, dict) else record
    raw_id = record.get("activityId") or record.get("id")
    if raw_id is not None and (isinstance(raw_id, bool) or not isinstance(raw_id, (str, int))):
        raise InvalidRecord("invalid_activity_id")
    provider_id = str(raw_id) if raw_id is not None else None
    if provider_id == "":
        raise InvalidRecord("invalid_activity_id")
    fields = {
        "distance_m": "distance", "elapsed_s": "elapsedDuration",
        "moving_s": "movingDuration", "average_hr": "averageHR",
        "average_cadence": "averageRunningCadenceInStepsPerMinute",
    }
    distance = _number(data.get("distance"), "distance")
    # `duration` is not substituted: timer and elapsed time can differ.
    elapsed = _number(data.get("elapsedDuration"), "elapsed_duration")
    moving = _number(data.get("movingDuration"), "moving_duration")
    hr = _number(data.get("averageHR"), "average_hr")
    cadence = _number(data.get("averageRunningCadenceInStepsPerMinute"), "average_cadence")
    label = None  # No verified Garmin field maps to our manual workout labels.
    if sport == "multisport":
        # A parent summary cannot safely be added to child run volume.
        sport = "other"
    return CanonicalActivity(
        provider_id, instant, source_time, instant.astimezone(zone).date().isoformat(),
        assumption, sport, subtype, distance, elapsed, moving, hr, cadence, label,
        {name: ("summaryDTO." if data is summary else "") + key
         for name, key in fields.items() if data.get(key) is not None},
    )
