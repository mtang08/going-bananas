"""Separate recovery signals with source-specific robust baselines, never a readiness score."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.checkin_models import Checkin
from app.metrics.contract import MetricResultData, QualityStatus, Status, canonical_json, config_hash, coverage_label
from app.metrics.engine import register
from app.models import RawObject, RecoveryObservation, SourceRecord
from app.services.timezone import athlete_tz

METRIC_ID = "recovery_multisignal_summary"
METHOD_VERSION = "v1"
WINDOW_DAYS = (7,)
DEPENDS_ON: tuple[str, ...] = ()
CONFIG = {"baseline_days": 60, "min_nights": 14, "established_nights": 28, "stale_days": 14,
          "stale_min_nights": 7, "robust_factor": .6745, "adverse_z": 1.5, "subjective_fatigue": 7,
          "hrv_transform": "ln", "statistics": {"sleep": "main_sleep_duration", "hrv": "last_night_average", "resting_hr": "daily_resting"},
          "valid_ranges": {"sleep": {"low_exclusive": 0, "high": 86400}, "hrv": {"low_exclusive": 0},
                           "resting_hr": {"low": 30, "high": 230}}, "partition_rule": "source_definition_device.v1"}
SIGNALS = ("sleep", "hrv", "resting_hr")


@dataclass(frozen=True)
class Observation:
    local_date: date
    metric: str
    value: float | None
    partition: str
    resolved: bool
    source_refs: dict


@dataclass(frozen=True)
class Subjective:
    observed_at: datetime
    id: str
    fatigue: float | None
    illness: str | None


def _valid(metric: str, value: float | None) -> bool:
    if value is None or not math.isfinite(value):
        return False
    return 0 < value <= 86400 if metric == "sleep" else 30 <= value <= 230 if metric == "resting_hr" else value > 0


def _unknown_device(partition: str) -> bool:
    try:
        value = json.loads(partition)
    except ValueError:
        return partition == "unknown"
    return isinstance(value, dict) and value.get("device_generation") == "unknown"


def signal_outcome(metric: str, current: Observation | None, history: list[Observation], on_date: date) -> dict:
    if metric not in SIGNALS:
        raise ValueError("invalid_recovery_metric")
    result: dict = {"status": "missing", "value": None, "baseline_state": "none", "valid_nights": 0,
                    "invalid_history_nights": 0, "z": None, "adverse": None, "baseline_median": None,
                    "baseline_mad": None, "deviation": None, "reason_codes": [], "quality_flags": [],
                    "partition": current.partition if current else None}
    if current is None:
        result["reason_codes"] = ["RECOVERY_MISSING"]
        return result
    if not current.resolved:
        result.update(status="invalid", reason_codes=["RECOVERY_UNRESOLVED"])
        return result
    if current.value is None:
        result["reason_codes"] = ["RECOVERY_MISSING"]
        return result
    if not _valid(metric, current.value):
        result.update(status="invalid", reason_codes=["RECOVERY_VALUE_INVALID"])
        return result
    result["value"] = round(current.value, 1)
    if _unknown_device(current.partition):
        result["quality_flags"].append("SOURCE_DEVICE_UNKNOWN")
    # Caller orders revisions oldest to newest; retain latest resolved night.
    latest = {}
    invalid_dates = set()
    for observation in history:
        if (observation.metric != metric or observation.partition != current.partition
                or not on_date - timedelta(days=60) <= observation.local_date < on_date):
            continue
        if observation.resolved:
            latest[observation.local_date] = observation
        else:
            invalid_dates.add(observation.local_date)
    valid = []
    for observation in latest.values():
        if _valid(metric, observation.value):
            valid.append(observation)
        else:
            invalid_dates.add(observation.local_date)
    result["invalid_history_nights"] = len(invalid_dates)
    count = len(valid)
    result.update(valid_nights=count, baseline_state="established" if count >= 28 else "provisional" if count >= 14 else "none")
    if sum(o.local_date >= on_date - timedelta(days=14) for o in valid) < 7:
        result["quality_flags"].append("BASELINE_STALE")
    transform = math.log if metric == "hrv" else float
    values = [transform(o.value) for o in valid if o.value is not None]
    if values:
        center = median(values)
        spread = median(abs(v - center) for v in values)
        deviation = transform(current.value) - center
        # HRV baseline statistics are explicitly in log units.
        digits = 3 if metric == "hrv" else 1
        result.update(baseline_median=round(center, digits), baseline_mad=round(spread, digits), deviation=round(deviation, digits))
    if count < 14:
        result.update(status="partial", reason_codes=["BASELINE_INSUFFICIENT"])
    elif spread == 0:
        result.update(status="partial", reason_codes=["MAD_ZERO"])
    else:
        z = .6745 * deviation / spread
        result.update(status="available", z=round(z, 2), adverse=z >= 1.5 if metric == "resting_hr" else z <= -1.5)
    return result


def _three_any(values: list[bool | None]) -> bool | None:
    return True if any(value is True for value in values) else False if all(value is False for value in values) else None


def night_outcome(on_date: date, observations: list[Observation], subjectives: list[Subjective]) -> dict:
    """Subjectives are already restricted to this athlete-local date by the caller."""
    signals = {metric: signal_outcome(metric, next((o for o in reversed(observations)
                                                  if o.metric == metric and o.local_date == on_date), None), observations, on_date)
               for metric in SIGNALS}
    ordered = sorted(subjectives, key=lambda s: (s.observed_at, s.id))
    fatigue = next((s.fatigue for s in reversed(ordered) if s.fatigue is not None), None)
    illness = next((s.illness for s in reversed(ordered) if s.illness is not None), None)
    subjective = _three_any([fatigue >= 7 if fatigue is not None else None,
                             illness in ("possible", "present") if illness is not None else None])
    physiological = _three_any([s["adverse"] for s in signals.values()])
    discordance = physiological != subjective if physiological is not None and subjective is not None else None
    reasons = sorted({r for s in signals.values() for r in s["reason_codes"]})
    flags = sorted({f for s in signals.values() for f in s["quality_flags"]})
    status = ("missing" if all(s["status"] == "missing" for s in signals.values()) and subjective is None else
              "partial" if any(s["status"] != "available" for s in signals.values()) else "available")
    return {"status": status, "quality_status": None if status == "missing" else "limited" if status == "partial" or flags else "good",
            "reason_codes": reasons, "quality_flags": flags,
            "value": {"local_date": on_date.isoformat(), **signals, "subjective_poor": subjective,
                      "discordance": discordance, "fatigue": fatigue, "illness": illness}}


def summary_outcome(nights: list[dict]) -> dict:
    if len(nights) != 7 or len({n["value"]["local_date"] for n in nights}) != 7:
        raise ValueError("seven_dated_nights_required")
    missing = sorted(n["value"]["local_date"] for n in nights
                     if not any(n["value"][metric]["value"] is not None for metric in SIGNALS))
    count = 7 - len(missing)
    flags = sorted({f for n in nights for f in n["quality_flags"]})
    return {"status": "missing" if count == 0 else "partial" if count < 7 else "available",
            "quality_status": coverage_label(count, 7), "reason_codes": ["RECOVERY_NIGHTS_MISSING"] if missing else [],
            "quality_flags": flags, "value": {"nights_total": 7, "nights_with_data": count,
                                               "missing_dates": missing, "coverage": round(count / 7, 3)}}


def _load_observations(session: Session, start: date, end: date) -> list[Observation]:
    rows = session.execute(select(RecoveryObservation, SourceRecord, RawObject).outerjoin(
        SourceRecord, RecoveryObservation.source_record_id == SourceRecord.id).outerjoin(
        RawObject, SourceRecord.raw_object_id == RawObject.id).where(
        RecoveryObservation.source_date >= start, RecoveryObservation.source_date <= end,
        RecoveryObservation.metric.in_(SIGNALS)).order_by(SourceRecord.fetched_at, RecoveryObservation.id)).all()
    result = []
    for observation, source, raw in rows:
        fields = source.fields if source else {}
        partition = canonical_json({"source_account_id": str(observation.source_account_id),
                                    "source_kind": source.source_kind if source else "unknown",
                                    "statistic": observation.statistic, "definition": observation.time_semantics,
                                    "device_generation": fields.get("device_generation") or "unknown"})
        refs = {"id": str(observation.id), "source_revision": observation.source_revision,
                "source_record_id": str(source.id) if source else None, "payload_hash": source.payload_hash if source else None,
                "raw_sha256": raw.sha256 if raw else None, "partition": partition,
                "value": observation.value, "source_date": observation.source_date.isoformat(),
                "source_rejected_reason": source.rejected_reason if source else None}
        result.append(Observation(observation.source_date, observation.metric, observation.value, partition,
                                  source is not None and source.rejected_reason is None, refs))
    return result


@register(METRIC_ID, METHOD_VERSION, DEPENDS_ON)
def compute(session: Session, subject_key: str) -> list[MetricResultData]:
    try:
        prefix, raw_date = subject_key.split(":", 1)
        on_date = date.fromisoformat(raw_date)
        if prefix not in ("night", "w7") or on_date.isoformat() != raw_date:
            raise ValueError
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_subject_key") from exc
    tz = athlete_tz(session)
    first = on_date - timedelta(days=6 if prefix == "w7" else 0)
    observations = _load_observations(session, first - timedelta(days=60), on_date)
    start_utc = datetime.combine(first, time.min, tzinfo=tz).astimezone(UTC)
    end_utc = datetime.combine(on_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    checkins = session.scalars(select(Checkin).where(Checkin.observed_at >= start_utc,
                                                    Checkin.observed_at < end_utc).order_by(Checkin.observed_at, Checkin.id)).all()
    nights = []
    for n in range((on_date - first).days + 1):
        day = first + timedelta(days=n)
        subjectives = [Subjective(c.observed_at, str(c.id), c.fatigue, c.illness) for c in checkins
                       if c.observed_at.astimezone(tz).date() == day]
        nights.append(night_outcome(day, observations, subjectives))
    outcome = summary_outcome(nights) if prefix == "w7" else nights[0]
    refs = {"recovery": [o.source_refs for o in observations],
            "checkins": [{"id": str(c.id), "version": c.version, "fatigue": c.fatigue, "illness": c.illness,
                          "observed_at": c.observed_at.isoformat()} for c in checkins],
            "sources": {"window_start": first.isoformat(), "as_of": on_date.isoformat(),
                        "baseline_start": (first - timedelta(days=60)).isoformat()}}
    return [MetricResultData(METRIC_ID, METHOD_VERSION, "window" if prefix == "w7" else "night", subject_key,
                             Status(outcome["status"]), tuple(outcome["reason_codes"]), tuple(outcome["quality_flags"]),
                             refs, (), config_hash(CONFIG), window_start=start_utc, window_end=end_utc,
                             window_label=subject_key, quality_status=QualityStatus(outcome["quality_status"])
                             if outcome["quality_status"] else None, value=outcome["value"], timezone=tz.key)]
