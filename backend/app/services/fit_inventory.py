"""Redacted FIT and Personal API shape inventory, without response values."""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime

from app.adapters.garmin.fit import DecodedFit, decode_fit_zip

_DATE_KEY = re.compile(r'^\d{4}-\d{2}-\d{2}(?:[T ].*)?$')
_NUMBER_KEY = re.compile(r'^[+-]?\d+(?:\.\d+)?$')
_PRIVATE_KEY = re.compile(r'(?:position|latitude|longitude|serial|token|secret|password|credential|authorization|access_key|(?:^|[_-])(?:lat|lon)(?:$|[_-]))', re.I)
_CAMEL_COORDINATE = re.compile(r'(?:Lat|Lon)(?:$|[A-Z])')


def _safe_key(key: object) -> str | None:
    value = str(key)
    if _PRIVATE_KEY.search(value) or _CAMEL_COORDINATE.search(value):
        return None
    if _DATE_KEY.fullmatch(value) or _NUMBER_KEY.fullmatch(value):
        return '<key>'
    return value


def _type_name(value: object) -> str:
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, (datetime, date)):
        return 'datetime' if isinstance(value, datetime) else 'date'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, (list, tuple)):
        return 'array'
    return 'unknown'


def merge_key_paths(values: Iterable[object]) -> dict[str, list[str]]:
    types: dict[str, set[str]] = defaultdict(set)
    def visit(value: object, path: str) -> None:
        if path:
            types[path].add(_type_name(value))
        if isinstance(value, dict):
            for key, child in value.items():
                safe = _safe_key(key)
                if safe is not None:
                    visit(child, f'{path}.{safe}' if path else safe)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child, f'{path}[]')
    for value in values:
        visit(value, '')
    return {key: sorted(types[key]) for key in sorted(types)}


def build_inventory(decoded: DecodedFit, api_shapes: dict) -> dict:
    intervals = [b-a for a, b in zip(decoded.stream.t_s, decoded.stream.t_s[1:])]
    safe_fields = {name: sorted(field for field in fields if _safe_key(field) is not None)
        for name, fields in decoded.field_names.items()}
    return {
        'schema_version': 'fit_inventory.v1',
        'sdk_version': decoded.sdk_version,
        'profile_version': decoded.profile_version,
        'message_counts': dict(sorted(decoded.message_inventory.items())),
        'field_names': safe_fields,
        'record_interval_s': {
            'count': len(intervals),
            'min': min(intervals) if intervals else None,
            'median': statistics.median(intervals) if intervals else None,
            'max': max(intervals) if intervals else None,
            'gaps_over_10s': sum(gap > 10 for gap in intervals),
        },
        'timer_segments': [list(segment) for segment in decoded.stream.timer_on],
        'presence': {
            'heart_rate': any(value is not None for value in decoded.stream.hr_bpm),
            'speed': any(value is not None for value in decoded.stream.speed_mps),
            'distance': any(value is not None for value in decoded.stream.distance_m),
            'altitude': any(value is not None for value in decoded.stream.altitude_m),
            'cadence': any(value is not None for value in decoded.stream.cadence),
            'timer_events': bool(decoded.stream.timer_on),
            'laps': bool(decoded.laps),
            'workout_steps': bool(decoded.steps),
        },
        'quality_flags': list(decoded.stream.quality_flags),
        'device_fields': sorted(decoded.device),
        'api_shapes': {str(name): merge_key_paths([shape]) for name, shape in api_shapes.items()
                       if _safe_key(name) is not None},
    }


def collect_inventory(source, activity_ids: Iterable[str]) -> dict:
    """Use caller-provided source only; no hidden client or live mode selection."""
    activities = []
    for activity_id in activity_ids:
        decoded = decode_fit_zip(source.download_activity(activity_id))
        shapes = {
            'activity_detail': source.activity_detail(activity_id),
            'activity_workouts': source.activity_workouts(activity_id),
        }
        activities.append(build_inventory(decoded, shapes))
    return {'schema_version': 'fit_inventory.v1', 'activities': activities}
