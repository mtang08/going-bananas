"""Read the recovery JSON shapes observed in a Garmin account export.

The caller preserves the original archive and member bytes. This module only
selects comparable daily observations; other health data stays in the archive.
"""

import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zipfile import ZipFile

_SLEEP = re.compile(r"(?:^|/)(?:\d{4}-\d{2}-\d{2}_){2}(\d+)_sleepData\.json$")
_HEALTH = re.compile(r"(?:^|/)(?:\d{4}-\d{2}-\d{2}_){2}(\d+)_healthStatusData\.json$")
_UDS = re.compile(r"(?:^|/)UDSFile_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.json$")


@dataclass(frozen=True)
class ExportRecoveryObservation:
    member_name: str
    source_record_identity: str
    account_owner: str
    metric: str
    source_date: date
    value: float
    unit: str
    statistic: str
    time_semantics: str
    source_field: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RecoveryExportScan:
    observations: tuple[ExportRecoveryObservation, ...]
    skipped: dict[str, int]


def _source_date(row: dict[str, Any]) -> date | None:
    value = row.get("calendarDate")
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and result >= 0 else None


def _gmt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def _rows(archive: ZipFile, name: str) -> list[Any]:
    try:
        data = json.loads(archive.read(name))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_recovery_json") from exc
    if not isinstance(data, list):
        raise ValueError("invalid_recovery_array")
    return data


def scan_recovery(archive: ZipFile) -> RecoveryExportScan:
    """Return supported sleep/RHR observations and explicit skipped row counts.

    Main sleep duration is the GMT sleep window minus awake seconds. This exact
    formula matched all 27 overlapping API sleepTimeSeconds observations in the
    inspected export. ``napList`` is excluded.
    """
    observations: list[ExportRecoveryObservation] = []
    skipped: Counter[str] = Counter()
    for name in sorted(archive.namelist()):
        sleep_match = _SLEEP.search(name)
        if sleep_match:
            owner = sleep_match.group(1)
            for row in _rows(archive, name):
                if not isinstance(row, dict):
                    skipped["sleep_invalid_row"] += 1
                    continue
                day = _source_date(row)
                start = _gmt(row.get("sleepStartTimestampGMT"))
                end = _gmt(row.get("sleepEndTimestampGMT"))
                awake = _number(row.get("awakeSleepSeconds"))
                if day is None or start is None or end is None or awake is None:
                    skipped["sleep_incomplete_or_invalid"] += 1
                    continue
                duration = (end - start).total_seconds() - awake
                if duration <= 0 or not math.isfinite(duration):
                    skipped["sleep_incomplete_or_invalid"] += 1
                    continue
                statistic = "main_sleep_duration"
                observations.append(ExportRecoveryObservation(
                    name, f"sleep:{day.isoformat()}:{statistic}", owner,
                    "sleep", day, duration, "s", statistic,
                    "garmin_sleep_calendar_date",
                    "sleepEndTimestampGMT-sleepStartTimestampGMT-awakeSleepSeconds", row,
                ))
            continue
        if _UDS.search(name):
            for row in _rows(archive, name):
                if not isinstance(row, dict):
                    skipped["uds_invalid_row"] += 1
                    continue
                owner = row.get("userProfilePK")
                day = _source_date(row)
                value = _number(row.get("restingHeartRate"))
                if isinstance(owner, bool) or not isinstance(owner, int) or day is None:
                    skipped["uds_missing_owner_or_date"] += 1
                    continue
                if value is None or value == 0:
                    skipped["uds_missing_or_invalid_resting_hr"] += 1
                    continue
                statistic = "daily_resting"
                observations.append(ExportRecoveryObservation(
                    name, f"resting_hr:{day.isoformat()}:{statistic}", str(owner),
                    "resting_hr", day, value, "bpm", statistic,
                    "garmin_heart_rate_calendar_date", "restingHeartRate", row,
                ))
            continue
        health_match = _HEALTH.search(name)
        if health_match:
            # Verified against API lastNightAvg for this observed export shape:
            # all 27 overlapping days have identical values. Keep this narrow
            # mapping; other Health Status metrics remain unsupported.
            owner = health_match.group(1)
            for row in _rows(archive, name):
                if not isinstance(row, dict):
                    skipped["health_status_invalid_row"] += 1
                    continue
                day = _source_date(row)
                metrics = row.get("metrics")
                matches = [metric for metric in metrics if isinstance(metric, dict)
                           and metric.get("type") == "HRV"] if isinstance(metrics, list) else []
                value = _number(matches[0].get("value")) if len(matches) == 1 else None
                if day is None or value is None or value == 0:
                    skipped["health_status_missing_or_invalid_hrv"] += 1
                    continue
                statistic = "last_night_average"
                observations.append(ExportRecoveryObservation(
                    name, f"hrv:{day.isoformat()}:{statistic}", owner,
                    "hrv", day, value, "ms", statistic,
                    "garmin_hrv_calendar_date", "metrics[type=HRV].value", row,
                ))
                skipped["health_status_other_metrics_unsupported"] += len(metrics) - 1 if isinstance(metrics, list) else 0
    return RecoveryExportScan(tuple(observations), dict(skipped))
