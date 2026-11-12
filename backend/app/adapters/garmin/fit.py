"""Pure FIT decoding into the frozen canonical activity contract."""
from __future__ import annotations

import hashlib
import io
import math
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from garmin_fit_sdk import Decoder, Stream

FIT_EPOCH_OFFSET = 631065600
MAX_FIT_BYTES = 50 * 1024 * 1024
SDK_VERSION = '21.221.0'
RUN_SPORTS = frozenset({'running', 'trail_running', 'treadmill_running'})
_PRIVATE_FIELD = re.compile(r'(?:position|latitude|longitude|serial|token|secret|password|credential)', re.I)


class FitDecodeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DecodedSession:
    start_at: datetime
    sport: str
    elapsed_s: float | None = None
    timer_s: float | None = None
    distance_m: float | None = None
    workout_rpe: float | None = None
    workout_feel: int | None = None


@dataclass(frozen=True)
class DecodedLap:
    lap_index: int
    start_at: datetime
    timer_s: float | None = None
    elapsed_s: float | None = None
    distance_m: float | None = None
    avg_speed_mps: float | None = None
    avg_hr_bpm: float | None = None
    max_hr_bpm: float | None = None
    lap_trigger: str | None = None
    wkt_step_index: int | None = None


@dataclass(frozen=True)
class DecodedStep:
    message_index: int
    duration_type: str
    step_name: str | None = None
    intensity: str | None = None
    duration_value: float | None = None
    target_type: str | None = None
    target_low: float | None = None
    target_high: float | None = None
    repeat_from: int | None = None
    repeat_count: int | None = None


@dataclass(frozen=True)
class DecodedStream:
    t_s: tuple[int, ...]
    hr_bpm: tuple[int | None, ...]
    speed_mps: tuple[float | None, ...]
    distance_m: tuple[float | None, ...]
    altitude_m: tuple[float | None, ...]
    cadence: tuple[float | None, ...]
    timer_on: tuple[tuple[int, int], ...]
    sample_count: int
    max_gap_s: int
    quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class DecodedFit:
    fit_sha256: str
    profile_version: str
    sdk_version: str
    session: DecodedSession
    laps: tuple[DecodedLap, ...]
    steps: tuple[DecodedStep, ...]
    stream: DecodedStream
    message_inventory: dict[str, int]
    device: dict
    field_names: dict[str, tuple[str, ...]]


def extract_fit(zip_bytes: bytes) -> bytes:
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith('.fit')]
            if len(members) != 1:
                raise FitDecodeError('zip_member_count')
            member = members[0]
            if member.file_size > MAX_FIT_BYTES:
                raise FitDecodeError('zip_member_too_large')
            chunks = []
            size = 0
            with archive.open(member) as source:
                while chunk := source.read(min(1024 * 1024, MAX_FIT_BYTES + 1 - size)):
                    size += len(chunk)
                    if size > MAX_FIT_BYTES:
                        raise FitDecodeError('zip_member_too_large')
                    chunks.append(chunk)
            return b''.join(chunks)
    except FitDecodeError:
        raise
    except (zipfile.BadZipFile, EOFError, OSError, ValueError, RuntimeError) as exc:
        raise FitDecodeError('bad_zip') from exc


def _instant(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        try:
            return datetime.fromtimestamp(value + FIT_EPOCH_OFFSET, UTC)
        except (OverflowError, ValueError, OSError):
            return None
    return None


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number.is_integer() else None


def _offset(value: object, start: datetime) -> int:
    instant = _instant(value)
    if instant is None:
        raise FitDecodeError('invalid_stream_time')
    seconds = (instant - start).total_seconds()
    if seconds < 0 or not seconds.is_integer():
        raise FitDecodeError('invalid_stream_time')
    return int(seconds)


def _channel(row: dict, enhanced: str, fallback: str) -> float | None:
    return _number(row.get(enhanced)) if row.get(enhanced) is not None else _number(row.get(fallback))


def _timer(events: list[dict], session: DecodedSession) -> tuple[tuple[tuple[int, int], ...], set[str]]:
    flags: set[str] = set()
    timer_events = [item for item in events if item.get('event') == 'timer']
    if not timer_events:
        return (), {'TIMER_EVENTS_MISSING'}
    try:
        ordered = sorted(((_offset(item.get('timestamp'), session.start_at), item.get('event_type'))
            for item in timer_events), key=lambda row: (row[0], 0 if row[1] in {'stop', 'stop_all'} else 1))
    except (FitDecodeError, TypeError):
        return (), {'TIMER_EVENTS_AMBIGUOUS'}
    start = None
    segments: list[tuple[int, int]] = []
    for second, kind in ordered:
        if kind == 'start':
            if start is not None:
                return (), {'TIMER_EVENTS_AMBIGUOUS'}
            start = second
        elif kind in {'stop', 'stop_all'}:
            if start is None or second < start:
                return (), {'TIMER_EVENTS_AMBIGUOUS'}
            if second > start:
                segments.append((start, second))
            start = None
        else:
            return (), {'TIMER_EVENTS_AMBIGUOUS'}
    if start is not None:
        if session.elapsed_s is None or not session.elapsed_s.is_integer() or session.elapsed_s < start:
            return (), {'TIMER_EVENTS_AMBIGUOUS'}
        segments.append((start, int(session.elapsed_s)))
        flags.add('TIMER_END_INFERRED')
    merged: list[tuple[int, int]] = []
    for first, last in segments:
        if merged and first <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(last, merged[-1][1]))
        else:
            merged.append((first, last))
    if session.timer_s is not None and abs(sum(b-a for a, b in merged) - session.timer_s) > max(1, session.timer_s * .01):
        flags.add('TIMER_MISMATCH')
    return tuple(merged), flags


def _stream(records: list[dict], events: list[dict], session: DecodedSession) -> DecodedStream:
    by_time: dict[int, dict[str, int | float | None]] = {}
    conflicted: dict[int, set[str]] = {}
    flags: set[str] = set()
    for record in records:
        second = _offset(record.get('timestamp'), session.start_at)
        values = {
            'hr': _integer(record.get('heart_rate')),
            'speed': _channel(record, 'enhanced_speed', 'speed'),
            'distance': _number(record.get('distance')),
            'altitude': _channel(record, 'enhanced_altitude', 'altitude'),
            'cadence': _number(record.get('cadence')),
        }
        if second not in by_time:
            by_time[second] = values
            conflicted[second] = set()
        else:
            previous = by_time[second]
            for key, value in values.items():
                if key not in conflicted[second] and previous[key] != value:
                    previous[key] = None
                    conflicted[second].add(key)
                    flags.add('DUPLICATE_RECORD_CONFLICT')
    times = tuple(sorted(by_time))
    timer_on, timer_flags = _timer(events, session)
    flags.update(timer_flags)
    return DecodedStream(times,
        tuple(cast(int | None, by_time[t]['hr']) for t in times),
        tuple(cast(float | None, by_time[t]['speed']) for t in times),
        tuple(cast(float | None, by_time[t]['distance']) for t in times),
        tuple(cast(float | None, by_time[t]['altitude']) for t in times),
        tuple(cast(float | None, by_time[t]['cadence']) for t in times),
        timer_on, len(times), max((b-a for a, b in zip(times, times[1:])), default=0),
        tuple(sorted(flags)))


def _step(message: dict) -> DecodedStep:
    message_index = _integer(message.get('message_index'))
    if message_index is None:
        raise FitDecodeError('decode_failed')
    duration_type = str(message.get('duration_type', ''))
    target_type = message.get('target_type')
    raw_duration = _number(message.get('duration_value'))
    repeat = duration_type.startswith('repeat_')
    if repeat:
        duration = raw_duration
    elif duration_type == 'time':
        duration = raw_duration / 1000 if raw_duration is not None else None
    elif duration_type == 'distance':
        duration = raw_duration / 100 if raw_duration is not None else None
    else:
        duration = raw_duration
    low = _number(message.get('custom_target_value_low'))
    high = _number(message.get('custom_target_value_high'))
    if target_type == 'speed':
        low = low / 1000 if low is not None else None
        high = high / 1000 if high is not None else None
    elif target_type == 'heart_rate':
        low = low - 100 if low is not None and low > 100 else None
        high = high - 100 if high is not None and high > 100 else None
    elif target_type == 'open':
        low = high = None
    return DecodedStep(message_index, duration_type,
        message.get('wkt_step_name'), message.get('intensity'), duration,
        target_type, low, high,
        _integer(message.get('duration_value')) if repeat else None,
        _integer(message.get('target_value')) if repeat else None)


def decode_fit(fit_bytes: bytes) -> DecodedFit:
    def decoder() -> Decoder:
        return Decoder(Stream.from_byte_array(bytearray(fit_bytes)))
    if not decoder().is_fit():
        raise FitDecodeError('invalid_fit')
    if not decoder().check_integrity():
        raise FitDecodeError('invalid_crc')
    try:
        raw_messages, errors = decoder().read(apply_scale_and_offset=True,
            convert_datetimes_to_dates=False, convert_types_to_strings=True,
            expand_sub_fields=False, expand_components=True)
    except Exception as exc:
        raise FitDecodeError('decode_failed') from exc
    if errors:
        raise FitDecodeError('decode_failed')
    messages = cast(dict[str, list[dict[str, Any]]], raw_messages)
    sessions = messages.get('session_mesgs', [])
    if len(sessions) != 1:
        raise FitDecodeError('missing_session' if not sessions else 'ambiguous_session')
    session_row = sessions[0]
    start = _instant(session_row.get('start_time'))
    if start is None:
        raise FitDecodeError('missing_start')
    sub_sport = session_row.get('sub_sport')
    if session_row.get('sport') == 'running' and sub_sport in {'trail', 'treadmill', 'indoorRunning'}:
        sport = 'trail_running' if sub_sport == 'trail' else 'treadmill_running'
    else:
        sport = str(sub_sport) if sub_sport in RUN_SPORTS else str(session_row.get('sport', 'unknown'))
    rpe = _number(session_row.get('workout_rpe'))
    rpe = rpe / 10 if rpe is not None and 0 <= rpe <= 100 else None
    feel = _integer(session_row.get('workout_feel'))
    feel = feel if feel is not None and 0 <= feel <= 100 else None
    session = DecodedSession(start, sport, _number(session_row.get('total_elapsed_time')),
        _number(session_row.get('total_timer_time')), _number(session_row.get('total_distance')),
        rpe, feel)
    laps = tuple(DecodedLap(index, lap_start,
        _number(item.get('total_timer_time')), _number(item.get('total_elapsed_time')),
        _number(item.get('total_distance')),
        _channel(item, 'enhanced_avg_speed', 'avg_speed'),
        _number(item.get('avg_heart_rate')), _number(item.get('max_heart_rate')),
        item.get('lap_trigger'), _integer(item.get('wkt_step_index')))
        for index, item in enumerate(messages.get('lap_mesgs', []))
        if (lap_start := _instant(item.get('start_time'))) is not None)
    steps = tuple(_step(item) for item in sorted(messages.get('workout_step_mesgs', []),
        key=lambda item: _integer(item.get('message_index')) or 0))
    stream = _stream(messages.get('record_mesgs', []), messages.get('event_mesgs', []), session)
    inventory = {name: len(rows) for name, rows in messages.items()}
    field_names = {name: tuple(sorted({key for row in rows for key in row
        if not _PRIVATE_FIELD.search(key)})) for name, rows in messages.items()}
    device = {}
    for source in [*messages.get('file_id_mesgs', []), *messages.get('device_info_mesgs', [])]:
        for key in ('manufacturer', 'product', 'software_version'):
            if source.get(key) is not None:
                device[key] = source[key]
    return DecodedFit(hashlib.sha256(fit_bytes).hexdigest(), str(int.from_bytes(fit_bytes[2:4], 'little')),
        SDK_VERSION, session, laps, steps, stream, inventory, device, field_names)


def decode_fit_zip(zip_bytes: bytes) -> DecodedFit:
    return decode_fit(extract_fit(zip_bytes))
