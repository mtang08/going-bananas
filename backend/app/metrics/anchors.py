from __future__ import annotations

import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.metrics.contract import sha256_json
from app.models import AppState, ProfileVersion
from app.planning_models import IntensityAnchor

KIND_UNIT = {
    'hr_aerobic_upper': 'bpm', 'hr_threshold_lower': 'bpm',
    'speed_aerobic_upper': 'mps', 'speed_threshold_lower': 'mps',
    'performance_5k': 's', 'performance_1mile': 's',
    'performance_3min': 'm', 'performance_20_30min': 'mps',
}
PROTOCOLS = frozenset(('race_5k', 'time_trial_5k', 'time_trial_1mile', 'time_trial_3min',
                       'time_trial_20_30min', 'workout_derived', 'lab_test', 'manual'))
CONFIDENCES = frozenset(('high', 'moderate', 'low', 'insufficient'))


@dataclass(frozen=True)
class ActiveAnchor:
    anchor_key: str
    kind: str
    value_low: float
    confidence: str
    review_after: date
    valid_from: date
    content_hash: str


def _content(anchor: IntensityAnchor) -> dict[str, Any]:
    return {key: str(value) if isinstance(value, uuid.UUID) else value for key, value in {
        'anchor_key': anchor.anchor_key, 'kind': anchor.kind,
        'value_low': anchor.value_low, 'value_high': anchor.value_high,
        'unit': anchor.unit, 'protocol': anchor.protocol,
        'confidence': anchor.confidence, 'calibrated_at': anchor.calibrated_at,
        'valid_from': anchor.valid_from, 'review_after': anchor.review_after,
        'source_activity_id': anchor.source_activity_id,
        'source_event_id': anchor.source_event_id, 'proposal_id': anchor.proposal_id,
        'conditions': anchor.conditions, 'notes': anchor.notes,
        'supersedes_key': anchor.supersedes_key,
    }.items()}


def anchor_content_hash(anchor: IntensityAnchor) -> str:
    return sha256_json(_content(anchor))


def anchor_data(anchor: IntensityAnchor) -> dict[str, Any]:
    return {'id': anchor.id, **_content(anchor), 'status': anchor.status,
            'content_hash': anchor_content_hash(anchor)}


def active_anchors(session: Session, on_date: date) -> dict[str, ActiveAnchor]:
    rows = session.scalars(select(IntensityAnchor).where(
        IntensityAnchor.valid_from <= on_date,
        IntensityAnchor.status.in_(('active', 'expired')))
        .order_by(IntensityAnchor.valid_from, IntensityAnchor.calibrated_at,
                  IntensityAnchor.anchor_key)).all()
    child_keys = {row.supersedes_key for row in rows if row.supersedes_key}
    selected: dict[str, IntensityAnchor] = {}
    for row in rows:
        if row.anchor_key in child_keys:
            continue
        previous = selected.get(row.kind)
        if previous is None or (row.valid_from, row.calibrated_at, row.anchor_key) > (
                previous.valid_from, previous.calibrated_at, previous.anchor_key):
            selected[row.kind] = row
    return {kind: ActiveAnchor(row.anchor_key, kind, row.value_low, row.confidence,
                               row.review_after, row.valid_from, anchor_content_hash(row))
            for kind, row in selected.items()}


def anchor_set_hash(anchors: Iterable[ActiveAnchor]) -> str | None:
    rows = sorted((anchor.kind, anchor.anchor_key, anchor.content_hash) for anchor in anchors)
    return sha256_json(rows) if rows else None


def _fail(code: str, message: str, status: int = 422) -> None:
    from app.api.core import fail
    fail(code, message, status)


def _profile_zone(session: Session) -> ZoneInfo:
    profile = session.scalar(select(ProfileVersion).order_by(ProfileVersion.version.desc()).limit(1))
    return ZoneInfo(profile.timezone if profile else 'America/New_York')


def _validate_value(kind: str, low: float, high: float | None) -> None:
    if not math.isfinite(low) or (high is not None and not math.isfinite(high)):
        _fail('invalid_anchor_value', 'Anchor values must be finite')
    if high is not None and high < low:
        _fail('invalid_anchor_range', 'Anchor upper value must be at least the lower value')
    for value in (low, high):
        if value is None:
            continue
        if kind.startswith('hr_') and not 30 <= value <= 230:
            _fail('invalid_anchor_value', 'Heart rate anchor must be 30 to 230 bpm')
        if kind.startswith('speed_') and not 0 < value <= 10:
            _fail('invalid_anchor_value', 'Speed anchor must be above zero and at most 10 m/s')
        if kind.startswith('performance_') and value <= 0:
            _fail('invalid_anchor_value', 'Performance anchor must be positive')


def create_anchor(session: Session, fields: dict[str, Any]) -> dict[str, Any]:
    session.execute(text('SELECT pg_advisory_xact_lock(71382413)'))
    state = session.get(AppState, 1, with_for_update=True)
    if state is None or state.planning_authority != 'calendar':
        _fail('planning_not_active', 'Calendar planning is not active', 409)
    allowed = {'kind', 'value_low', 'value_high', 'unit', 'protocol', 'confidence',
               'calibrated_at', 'valid_from', 'review_after', 'source_activity_id',
               'source_event_id', 'proposal_id', 'conditions', 'notes', 'supersedes_key'}
    if set(fields) - allowed:
        _fail('invalid_anchor_fields', 'Unknown anchor fields')
    required = {'kind', 'value_low', 'unit', 'protocol', 'confidence', 'calibrated_at', 'valid_from'}
    if required - set(fields):
        _fail('invalid_anchor_fields', 'Missing anchor fields')
    kind = fields['kind']
    if kind not in KIND_UNIT or fields['unit'] != KIND_UNIT[kind]:
        _fail('invalid_anchor_unit', 'Anchor kind and unit do not match')
    if fields['protocol'] not in PROTOCOLS or fields['confidence'] not in CONFIDENCES:
        _fail('invalid_anchor_fields', 'Invalid anchor protocol or confidence')
    try:
        if isinstance(fields['value_low'], bool) or isinstance(fields.get('value_high'), bool):
            _fail('invalid_anchor_value', 'Anchor values must be numbers')
        low = float(fields['value_low'])
        high = float(fields['value_high']) if fields.get('value_high') is not None else None
    except (TypeError, ValueError, OverflowError):
        _fail('invalid_anchor_value', 'Anchor values must be numbers')
        raise AssertionError('unreachable')
    _validate_value(kind, low, high)
    calibrated = fields['calibrated_at']
    if isinstance(calibrated, str):
        try:
            calibrated = datetime.fromisoformat(calibrated.replace('Z', '+00:00'))
        except ValueError:
            _fail('invalid_anchor_date', 'Invalid calibration timestamp')
    if not isinstance(calibrated, datetime) or calibrated.tzinfo is None or calibrated.utcoffset() is None:
        _fail('invalid_anchor_date', 'Calibration timestamp requires an offset')
    valid_from = fields['valid_from']
    if isinstance(valid_from, str):
        try:
            valid_from = date.fromisoformat(valid_from)
        except ValueError:
            _fail('invalid_anchor_date', 'Invalid effective date')
    if not isinstance(valid_from, date) or isinstance(valid_from, datetime):
        _fail('invalid_anchor_date', 'Invalid effective date')
    review_after = fields.get('review_after')
    if review_after is None:
        review_after = calibrated.astimezone(_profile_zone(session)).date() + timedelta(days=84)
    elif isinstance(review_after, str):
        try:
            review_after = date.fromisoformat(review_after)
        except ValueError:
            _fail('invalid_anchor_date', 'Invalid review date')
    if not isinstance(review_after, date) or isinstance(review_after, datetime):
        _fail('invalid_anchor_date', 'Invalid review date')
    rows = session.scalars(select(IntensityAnchor).where(IntensityAnchor.kind == kind)
                           .order_by(IntensityAnchor.valid_from, IntensityAnchor.calibrated_at,
                                     IntensityAnchor.anchor_key)).all()
    superseded_keys = {row.supersedes_key for row in rows if row.supersedes_key}
    terminal_rows = [row for row in rows if row.anchor_key not in superseded_keys]
    predecessor = max(terminal_rows, key=lambda row: (row.valid_from, row.calibrated_at, row.anchor_key)) if terminal_rows else None
    supersedes_key = fields.get('supersedes_key')
    if predecessor is None and supersedes_key is not None:
        _fail('anchor_supersede_required', 'No predecessor exists for this anchor', 409)
    if predecessor is not None:
        if supersedes_key is None:
            _fail('anchor_supersede_required', 'Specify the anchor being superseded', 409)
        if supersedes_key != predecessor.anchor_key:
            _fail('anchor_superseded', 'The selected predecessor has a newer successor', 409)
        if valid_from < predecessor.valid_from:
            _fail('anchor_backdate_conflict', 'Successor cannot predate its predecessor')
    base_key = f'{kind}-{valid_from.isoformat()}'
    existing_keys = {row.anchor_key for row in session.scalars(
        select(IntensityAnchor).where(IntensityAnchor.anchor_key.like(base_key + '%')))}
    key = base_key
    suffix = 2
    while key in existing_keys:
        key = f'{base_key}-{suffix}'
        suffix += 1
    if len(key) > 40:
        _fail('invalid_anchor_key', 'Anchor key exceeds storage limit')
    anchor = IntensityAnchor(anchor_key=key, kind=kind, value_low=low, value_high=high,
        unit=fields['unit'], protocol=fields['protocol'], confidence=fields['confidence'],
        status='active', calibrated_at=calibrated.astimezone(UTC), valid_from=valid_from,
        review_after=review_after, source_activity_id=fields.get('source_activity_id'),
        source_event_id=fields.get('source_event_id'), proposal_id=fields.get('proposal_id'),
        conditions=fields.get('conditions'), notes=fields.get('notes'),
        supersedes_key=supersedes_key)
    session.add(anchor)
    session.flush()
    return anchor_data(anchor)
