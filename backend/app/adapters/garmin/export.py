"""Bounded reader for Garmin's account-export activity summaries.

The archive is inspected in place. No member is extracted to a filesystem path.
This mapping was checked against twelve matching Personal API summaries.
"""

from __future__ import annotations

import hashlib
import json
import math
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from zipfile import ZipFile, ZipInfo

MAX_ENTRIES = 10_000
MAX_EXPANDED = 5 * 1024**3
MAX_MEMBER = 1024**3
MAX_RATIO = 1_000
ACTIVITY_SUFFIX = "summarizedActivities.json"


class ExportError(ValueError):
    """Safe, payload-free archive/record error code."""


@dataclass(frozen=True)
class ExportActivity:
    original: dict
    normalized: dict
    owner: str
    member_name: str
    member_sha256: str
    row_index: int


@dataclass(frozen=True)
class ActivityScan:
    activities: tuple[ExportActivity, ...]
    member_count: int
    expanded_bytes: int


def safe_inventory(archive: ZipFile) -> tuple[ZipInfo, ...]:
    infos = tuple(archive.infolist())
    if len(infos) > MAX_ENTRIES:
        raise ExportError("archive_too_many_entries")
    names: set[str] = set()
    expanded = 0
    for info in infos:
        name = info.filename
        parts = PurePosixPath(name).parts
        path_parts = name.rstrip("/").split("/")
        if (not name or name.startswith(("/", "\\")) or "\\" in name
                or any(part in ("", ".", "..") for part in path_parts)
                or any(":" in part for part in parts)
                or name in names):
            raise ExportError("unsafe_archive_path")
        names.add(name)
        mode = info.external_attr >> 16
        if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ExportError("unsafe_archive_entry")
        if info.flag_bits & 1:
            raise ExportError("encrypted_archive_entry")
        if info.file_size > MAX_MEMBER:
            raise ExportError("archive_member_too_large")
        expanded += info.file_size
        if expanded > MAX_EXPANDED:
            raise ExportError("archive_too_large")
        if info.file_size and info.file_size / max(info.compress_size, 1) > MAX_RATIO:
            raise ExportError("archive_compression_ratio")
    return infos


def _nonnegative(value: object, code: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise ExportError(code)
    return float(value)


def _epoch_ms(value: object, code: str) -> datetime:
    number = _nonnegative(value, code)
    if number is None:
        raise ExportError(code)
    try:
        result = datetime.fromtimestamp(number / 1000, UTC)
    except (ValueError, OverflowError, OSError) as exc:
        raise ExportError(code) from exc
    if not 2000 <= result.year <= 2100:
        raise ExportError(code)
    return result


def normalize_export_activity(row: dict) -> dict:
    """Convert verified export fields to the API-shaped summary parser input."""
    if not isinstance(row, dict):
        raise ExportError("invalid_activity_record")
    activity_id = row.get("activityId")
    owner = row.get("userProfileId")
    if type(activity_id) is not int or activity_id <= 0 or type(owner) is not int or owner <= 0:
        raise ExportError("invalid_activity_identity")
    start = _epoch_ms(row.get("startTimeGmt"), "invalid_activity_start")
    kind = row.get("activityType")
    if not isinstance(kind, str) or not kind:
        raise ExportError("invalid_activity_type")
    normalized: dict = {
        "activityId": activity_id,
        "ownerId": owner,
        "startTimeGMT": start.isoformat(),
        "activityType": {"typeKey": kind},
    }
    for source, target, scale in (
        ("distance", "distance", 0.01),
        ("elapsedDuration", "elapsedDuration", 0.001),
        ("movingDuration", "movingDuration", 0.001),
        ("avgHr", "averageHR", 1),
    ):
        value = _nonnegative(row.get(source), "invalid_activity_" + source)
        if value is not None:
            normalized[target] = value * scale
    return normalized


def scan_activities(archive: ZipFile) -> ActivityScan:
    infos = safe_inventory(archive)
    candidates = [info for info in infos if PurePosixPath(info.filename).name.endswith(ACTIVITY_SUFFIX)]
    if len(candidates) != 1:
        raise ExportError("activity_member_count")
    member = candidates[0]
    raw = archive.read(member)
    if len(raw) != member.file_size:
        raise ExportError("archive_member_size_mismatch")
    try:
        root = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ExportError("invalid_activity_json") from exc
    if not (isinstance(root, list) and len(root) == 1 and isinstance(root[0], dict)
            and isinstance(root[0].get("summarizedActivitiesExport"), list)):
        raise ExportError("invalid_activity_schema")
    records = root[0]["summarizedActivitiesExport"]
    digest = hashlib.sha256(raw).hexdigest()
    activities = []
    owners: set[str] = set()
    identities: set[int] = set()
    for index, row in enumerate(records):
        normalized = normalize_export_activity(row)
        owner = str(row["userProfileId"])
        if row["activityId"] in identities:
            raise ExportError("duplicate_activity_id")
        owners.add(owner)
        identities.add(row["activityId"])
        activities.append(ExportActivity(row, normalized, owner, member.filename, digest, index))
    if len(owners) != 1:
        raise ExportError("mixed_activity_owner")
    return ActivityScan(tuple(activities), len(infos), sum(info.file_size for info in infos))
