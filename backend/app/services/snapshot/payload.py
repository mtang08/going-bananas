"""Snapshot payload."""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.calendar_structure import work_signature
from app.domain.local_time import date_in_zone
from app.domain.session_class import LONG_RECIPE, QUALITY_RECIPES, classify, expected_rpe, rpe_mismatch
from app.services.exceptions.vocab import NON_TERMINAL_FINDING, RULE_VERSION
from app.services.operations import OPERATIONS
from app.services.proposals.schema import (
    BLOCK_REVIEW_LEAD_DAYS,
    HORIZON_MAX_DAYS,
    HORIZON_MIN_DAYS,
    HORIZON_OPS,
    scope,
)
from app.services.snapshot.common import (
    AEROBIC_RECENT_MAX,
    BLOCK,
    CALIB,
    DAILY,
    DATASETS,
    DRILL_DOWN_QUERIES,
    EXCEPTION,
    FINDING_EVIDENCE_MAX,
    KEY_SESSIONS_MAX,
    LIVE_PATCH,
    NOT_DONE_MAX,
    OPEN_FINDINGS_MAX,
    OPEN_PATCHES_MAX,
    POST_EVENT,
    PROGRESSION_GROUPS_MAX,
    PROGRESSION_POINT_KEYS,
    PROGRESSION_POINTS_MAX,
    QUALITY_OP,
    RACE,
    RECENT_RPE_MAX,
    ROLLING,
    SNAPSHOT_SCHEMA,
    SUMMARY_DAYS,
    SUMMARY_FINDINGS_MAX,
    SUMMARY_PATCHES_MAX,
    UNPLANNED_MAX,
    SnapshotInputs,
    day_between,
    parse_day,
    parse_instant,
    row_view,
    strip_private,
    to_wire,
)
from app.services.weekly_digest import DIGEST_SCHEMA, HEADLINE_KINDS, NOT_DONE_OUTCOMES
from app.services.workout_progression import assemble_groups, session_point

EVENT_KEYS = (
    "event_id",
    "name",
    "event_date",
    "distance_m",
    "purpose",
    "goal_time_s",
    "goal_pace_s_per_km",
    "rank",
    "status",
    "result_s",
)


def active_review_date(inputs: SnapshotInputs) -> date | None:
    block = inputs.active_block
    return parse_day(block["review_date"]) if block and block.get("review_date") else None


def section_window(operation: str, section: str, inputs: SnapshotInputs) -> tuple[date, date]:
    day = inputs.as_of
    if section == "calendar":
        if operation == RACE:
            return day, day + timedelta(days=HORIZON_MAX_DAYS)
        if operation == POST_EVENT:
            return day, day + timedelta(days=13)
        if operation == EXCEPTION:
            return day - timedelta(days=7), day + timedelta(days=6)
        start = day - timedelta(days={DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28}[operation])
        if operation == ROLLING:
            return start, scope(ROLLING, day, active_review_date(inputs))[1]
        if operation == BLOCK:
            return start, day + timedelta(days=HORIZON_MAX_DAYS)
        return start, day + timedelta(days=3 if operation == DAILY else 13)
    if section == "exposures":
        return day - timedelta(
            days={DAILY: 2, ROLLING: 13, QUALITY_OP: 13, BLOCK: 27, RACE: 13, CALIB: 83, EXCEPTION: 2, POST_EVENT: 13}[
                operation
            ]
        ), day
    if section == "symptoms":
        days = 14 if operation in {DAILY, EXCEPTION} else 28
        if operation == BLOCK and inputs.active_block:
            return parse_day(inputs.active_block["start_date"]), day
        return day - timedelta(days=days - 1), day
    if section == "recovery":
        days = {DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28, EXCEPTION: 3, POST_EVENT: 14}[operation]
        return day - timedelta(days=days - 1), day
    raise ValueError("unknown_section")


def _safe_revision(value: dict | None) -> dict | None:
    if value is None:
        return None
    allowed = {
        "local_date",
        "slot",
        "kind",
        "recipe_id",
        "custom",
        "placeholder",
        "locked",
        "intent",
        "planned_duration_s",
        "planned_distance_m",
        "structure",
        "strength_slot_id",
    }
    return {key: value[key] for key in allowed if key in value}


def _safety_guard(inputs: SnapshotInputs) -> dict:
    first = inputs.now - timedelta(hours=72)
    recent = [c for c in inputs.checkins if first <= parse_instant(c["observed_at"]) <= inputs.now]
    severities = [
        float(sym["severity"]) for c in recent for sym in c.get("symptoms", []) if sym.get("severity") is not None
    ]
    return {
        "window_hours": 72,
        "gait_change_yes": any(c.get("gait_change") == "yes" for c in recent),
        "max_symptom_severity": max(severities) if severities else None,
        "illness_present": any(c.get("illness") == "present" for c in recent),
        "clinical_restriction_active": bool(inputs.clinical_restriction and inputs.clinical_restriction.strip()),
    }


def _metric_view(row: dict) -> dict:
    return row_view(
        row,
        (
            "result_id",
            "metric_id",
            "method_version",
            "subject_type",
            "subject_key",
            "window_label",
            "status",
            "quality_status",
            "value",
            "unit",
            "reason_codes",
            "quality_flags",
            "anchor_keys",
            "calculated_at",
        ),
    )


def _session_view(row: dict, completion: dict | None) -> dict:
    result = row_view(
        row,
        (
            "session_uid",
            "revision",
            "local_date",
            "slot",
            "kind",
            "recipe_id",
            "custom",
            "placeholder",
            "intent",
            "certainty",
            "planned_duration_s",
            "planned_distance_m",
            "structure",
            "strength_slot_id",
            "brief",
        ),
    )
    if row.get("locked"):
        result["locked"] = True
    result["is_original"] = row["revision"] == 1
    result["completion_status"] = completion["status"] if completion else None
    if (
        completion
        and completion.get("match_method") == "user_marked"
        and completion["status"] == "completed_as_planned"
    ):
        result["self_reported"] = True
    result["modification_reason"] = completion.get("modification_reason") if completion else None
    return result


def _classify(recipe: str | None) -> str:
    if recipe == LONG_RECIPE:
        return "long"
    if recipe in QUALITY_RECIPES:
        return "quality"
    return "easy" if recipe else "unplanned"


def _completed_lifts(inputs: SnapshotInputs, start: date, end: date, sessions: dict[str, dict]) -> list[dict]:
    slots = {str(s["slot_id"]): s for s in inputs.strength_slots}
    by_strong = {str(c["strong_workout_id"]): c for c in inputs.completions if c.get("strong_workout_id")}
    lifts = []
    for row in inputs.strong_workouts:
        if day_between(row.get("local_date"), start, end):
            completion = by_strong.get(str(row["strong_workout_id"]))
            lifts.append(
                dict(
                    row_view(row, ("strong_workout_id", "local_date", "workout_name", "duration_s", "rpe")),
                    source="strong",
                    session_uid=completion["session_uid"] if completion else None,
                )
            )
    for completion in inputs.completions:
        planned = sessions.get(str(completion["session_uid"]))
        if (
            planned
            and planned["kind"] == "strength"
            and day_between(planned["local_date"], start, end)
            and completion.get("match_method") == "user_marked"
            and completion["status"] == "completed_as_planned"
            and not any(completion.get(key) for key in ("strong_workout_id", "activity_id", "manual_session_id"))
        ):
            lifts.append(
                {
                    "source": "self_reported",
                    "session_uid": planned["session_uid"],
                    "strong_workout_id": None,
                    "local_date": planned["local_date"],
                    "workout_name": None,
                    "duration_s": None,
                    "rpe": None,
                }
            )
    for lift in lifts:
        planned = sessions.get(str(lift["session_uid"])) or {}
        slot_id = planned.get("strength_slot_id")
        slot = slots.get(str(slot_id)) or {}
        lift.update(
            strength_slot_id=slot_id,
            planned_slot_label=slot.get("label"),
            planned_lower_body_cost=slot.get("lower_body_cost"),
        )
    return sorted(lifts, key=lambda row: (str(row["local_date"]), str(row["strong_workout_id"] or row["session_uid"])))


def _completed_exposures(inputs: SnapshotInputs, operation: str) -> dict:
    start, end = section_window(operation, "exposures", inputs)
    by_activity = {str(c["activity_id"]): c for c in inputs.completions if c.get("activity_id")}
    sessions = {str(s["session_uid"]): s for s in inputs.sessions}
    runs = []
    for row in inputs.runs:
        if not day_between(row.get("local_date"), start, end):
            continue
        completion = by_activity.get(str(row["activity_id"]))
        planned = sessions.get(str(completion["session_uid"])) if completion else None
        recipe = planned.get("recipe_id") if planned else None
        if operation == CALIB and recipe not in {"REC003", "REC004", "REC005", "REC009"}:
            continue
        view = row_view(row, ("activity_id", "local_date", "sport", "timer_s", "distance_m", "rpe", "rpe_source"))
        view.update(
            session_uid=completion["session_uid"] if completion else None,
            planned_recipe_id=recipe,
            completion_status=completion["status"] if completion else None,
        )
        view["class"] = _classify(recipe)
        runs.append(view)
    runs.sort(key=lambda row: (str(row["local_date"]), str(row["activity_id"])))
    if operation == CALIB:
        return {"window_days": 84, "runs": runs}
    return {
        "window_days": {DAILY: 3, ROLLING: 14, QUALITY_OP: 14, BLOCK: 28, RACE: 14, EXCEPTION: 3, POST_EVENT: 14}[
            operation
        ],
        "runs": runs,
        "lifts": _completed_lifts(inputs, start, end, sessions),
    }


def _symptoms(inputs: SnapshotInputs, operation: str) -> dict:
    start, end = section_window(operation, "symptoms", inputs)
    reports = []
    responses = {}
    for checkin in inputs.checkins:
        if not day_between(checkin.get("local_date"), start, end):
            continue
        if checkin.get("activity_id") is not None and checkin.get("kind") == "delayed_followup":
            responses[str(checkin["activity_id"])] = row_view(
                checkin, ("checkin_id", "observed_at", "recorded_at", "hours_after_end", "pain_reported", "gait_change")
            )
        for symptom in checkin.get("symptoms", []):
            view = row_view(checkin, ("checkin_id", "observed_at", "local_date", "kind", "activity_id"))
            view.update(row_view(symptom, ("site", "side", "severity", "timing")))
            reports.append(view)
    reports.sort(key=lambda row: (str(row["observed_at"]), str(row["checkin_id"]), row["site"], row["timing"]))
    delayed_responses = []
    zone = ZoneInfo(inputs.timezone)
    for prompt in inputs.prompts:
        if prompt.get("kind") != "delayed_symptom":
            continue
        activity_id = str(prompt["activity_id"])
        if activity_id in responses or day_between(date_in_zone(parse_instant(prompt["opens_at"]), zone), start, end):
            delayed_responses.append(
                {
                    **row_view(prompt, ("prompt_id", "kind", "activity_id", "status", "opens_at", "closes_at")),
                    "response": responses.pop(activity_id, None),
                }
            )
    delayed_responses.extend(
        {"activity_id": activity_id, "response": response} for activity_id, response in responses.items()
    )
    return {"window_days": (end - start).days + 1, "reports": reports, "delayed_responses": delayed_responses}


def _data_quality(inputs: SnapshotInputs) -> dict:
    datasets = {}
    flags = []
    for dataset in DATASETS:
        complete = [
            parse_day(row["end_date"])
            for row in inputs.coverage
            if row.get("dataset") == dataset and row.get("status") == "complete"
        ]
        fresh = max(complete) if complete else None
        status = "missing" if fresh is None else "stale" if fresh < inputs.as_of - timedelta(days=2) else "fresh"
        datasets[dataset] = {"status": status, "fresh_through": fresh}
        if status != "fresh":
            flags.append(f"{dataset}_{status}")
    if not any(a.get("status") == "active" for a in inputs.anchors):
        flags.append("no_intensity_anchor")
    if inputs.active_block is None:
        flags.append("no_active_block")
    return {"datasets": datasets, "flags": sorted(flags)}


def _prior_decisions(inputs: SnapshotInputs, operation: str) -> list[dict]:
    if operation == BLOCK:
        uid = inputs.active_block.get("block_uid") if inputs.active_block else None
        rows = [r for r in inputs.block_decisions if uid is None or str(r.get("block_uid")) == str(uid)]
        return sorted(
            [
                row_view(
                    r,
                    (
                        "decision",
                        "from_version",
                        "to_version",
                        "rationale",
                        "confidence",
                        "decided_at",
                        "proposal_id",
                        "block_uid",
                    ),
                )
                for r in rows
            ],
            key=lambda r: str(r["decided_at"]),
        )
    if operation == CALIB:
        return [
            row_view(
                a,
                (
                    "anchor_key",
                    "kind",
                    "value_low",
                    "value_high",
                    "unit",
                    "protocol",
                    "confidence",
                    "status",
                    "calibrated_at",
                    "valid_from",
                    "review_after",
                    "supersedes_key",
                ),
            )
            for a in inputs.anchors
        ]
    proposals = sorted(inputs.proposals, key=lambda p: str(p.get("submitted_at")), reverse=True)
    if operation in {ROLLING, QUALITY_OP}:
        decided = {"accepted", "partially_accepted", "rejected"}
        proposals = [p for p in proposals if p.get("operation") == ROLLING and p.get("status") in decided][:2] + [
            p for p in proposals if p.get("operation") == EXCEPTION and p.get("status") in decided
        ][:3]
    else:
        proposals = proposals[:3]
    result = []
    completions = {str(c["session_uid"]): c for c in inputs.completions}
    patch_status = {str(p["proposal_id"]): p["status"] for p in inputs.exception_patches}
    for proposal in proposals:
        view = row_view(
            proposal, ("proposal_id", "operation", "status", "submitted_at", "decided_at", "headline", "next_check")
        )
        changes = []
        for change in proposal.get("changes", []):
            item = row_view(change, ("change_id", "op", "session_uid", "decision"))
            item["before"] = _safe_revision(change.get("before"))
            item["after"] = _safe_revision(change.get("after"))
            if "strength_omission" in change.get("material_flags", []):
                item.update(material_flags=["strength_omission"], reason=change["reason"])
            elif change.get("decision") == "accepted" and change.get("session_uid"):
                date_value = (change.get("after") or {}).get("local_date") or (change.get("before") or {}).get(
                    "local_date"
                )
                if date_value:
                    day = parse_day(date_value)
                    reports = [
                        row_view(sym, ("site", "side", "severity", "timing"))
                        for c in inputs.checkins
                        if day_between(c.get("local_date"), day, day + timedelta(days=3))
                        for sym in c.get("symptoms", [])
                    ]
                    item["outcome"] = {
                        "session_date": day,
                        "completion_status": (completions.get(str(change["session_uid"])) or {}).get("status"),
                        "symptom_reports_after": reports,
                    }
            changes.append(item)
        view["changes"] = changes
        if proposal.get("operation") == EXCEPTION:
            view["patch_status"] = patch_status.get(str(proposal.get("proposal_id")))
        result.append(view)
    return result


def _site_key(symptom: dict) -> str:
    return f"{str(symptom.get('site') or '').strip().lower()}|{symptom.get('side')}"


def _rpe_rows(inputs: SnapshotInputs) -> list[dict]:
    start = inputs.as_of - timedelta(days=SUMMARY_DAYS - 1)
    by_activity = {str(c["activity_id"]): c for c in inputs.completions if c.get("activity_id")}
    sessions = {str(s["session_uid"]): s for s in inputs.sessions}
    rows = []
    for run in inputs.runs:
        if not day_between(run.get("local_date"), start, inputs.as_of):
            continue
        completion = by_activity.get(str(run["activity_id"]))
        planned = sessions.get(str(completion["session_uid"])) if completion else None
        recipe = planned.get("recipe_id") if planned else None
        cls = classify(planned["kind"], recipe, planned.get("intent")) if planned else None
        rpe = float(run["rpe"]) if run.get("rpe") is not None else None
        expected = expected_rpe(recipe, cls) if cls else None
        rows.append(
            {
                "activity_id": run["activity_id"],
                "local_date": run["local_date"],
                "class": cls,
                "rpe": rpe,
                "rpe_source": run.get("rpe_source"),
                "expected_rpe": list(expected) if expected else None,
                "mismatch": rpe_mismatch(cls, recipe, rpe) if cls else None,
            }
        )
    rows.sort(key=lambda r: (str(r["local_date"]), str(r["activity_id"])), reverse=True)
    return rows


def _exceptions_section(inputs: SnapshotInputs) -> dict:
    last = inputs.as_of + timedelta(days=6)
    findings = sorted(
        (f for f in inputs.exception_findings if f.get("status") in NON_TERMINAL_FINDING),
        key=lambda f: (str(f.get("first_seen_at")), str(f.get("id"))),
        reverse=True,
    )[:OPEN_FINDINGS_MAX]
    patches = sorted(
        (p for p in inputs.exception_patches if p.get("status") in LIVE_PATCH),
        key=lambda p: (str(p.get("created_at")), str(p.get("id"))),
        reverse=True,
    )[:OPEN_PATCHES_MAX]
    upcoming = []
    for row in sorted(
        (s for s in inputs.sessions if day_between(s.get("local_date"), inputs.as_of, last)),
        key=lambda s: (str(s["local_date"]), s.get("slot") or 0, str(s["session_uid"])),
    ):
        cls = classify(row.get("kind") or "", row.get("recipe_id"), row.get("intent"))
        expected = expected_rpe(row.get("recipe_id"), cls)
        upcoming.append(
            {
                "session_uid": row["session_uid"],
                "local_date": row["local_date"],
                "kind": row.get("kind"),
                "class": cls,
                "expected_rpe": list(expected) if expected else None,
                "certainty": row.get("certainty"),
            }
        )
    return {
        "rule_version": RULE_VERSION,
        "review_recommended": list(inputs.review_recommended),
        "open_findings": [{**f, "evidence": list(f.get("evidence") or [])[:FINDING_EVIDENCE_MAX]} for f in findings],
        "open_patches": patches,
        "upcoming": upcoming,
        "recent_rpe": _rpe_rows(inputs)[:RECENT_RPE_MAX],
    }


def _exception_summary(inputs: SnapshotInputs) -> dict:
    start = inputs.as_of - timedelta(days=SUMMARY_DAYS - 1)
    since = inputs.now - timedelta(days=SUMMARY_DAYS)
    reviews = [
        parse_instant(p["decided_at"])
        for p in inputs.proposals
        if p.get("operation") in {ROLLING, BLOCK}
        and p.get("status") in {"accepted", "partially_accepted"}
        and p.get("decided_at")
    ]
    findings = sorted(
        (
            f
            for f in inputs.exception_findings
            if f.get("status") in NON_TERMINAL_FINDING or parse_instant(f["first_seen_at"]) >= since
        ),
        key=lambda f: (str(f.get("first_seen_at")), str(f.get("id"))),
        reverse=True,
    )[:SUMMARY_FINDINGS_MAX]
    patches = [
        p for p in inputs.exception_patches if p.get("status") in LIVE_PATCH or parse_day(p["window_end"]) >= start
    ][:SUMMARY_PATCHES_MAX]
    mismatch = {"easy_above": 0, "long_above": 0, "quality_above": 0, "quality_below": 0}
    for row in _rpe_rows(inputs):
        key = f"{row['class']}_{row['mismatch']}"
        if key in mismatch:
            mismatch[key] += 1
    days_by_site: dict[str, set[date]] = {}
    for checkin in inputs.checkins:
        if day_between(checkin.get("local_date"), start, inputs.as_of):
            for symptom in checkin.get("symptoms", []):
                days_by_site.setdefault(_site_key(symptom), set()).add(parse_day(checkin["local_date"]))
    sites: list[dict[str, Any]] = sorted(
        ({"site_key": key, "distinct_days_14": len(days)} for key, days in days_by_site.items() if len(days) >= 2),
        key=lambda s: (-s["distinct_days_14"], s["site_key"]),
    )
    finding_keys = (
        "id",
        "rule_code",
        "category",
        "severity",
        "status",
        "first_seen_at",
        "summary",
        "is_new_since_last_review",
    )
    patch_keys = ("id", "category", "severity", "window_start", "window_end", "status", "reassess_on")
    return {
        "window_start": start,
        "window_end": inputs.as_of,
        "since_last_review": date_in_zone(max(reviews), ZoneInfo(inputs.timezone)) if reviews else None,
        "findings": [row_view(f, finding_keys) for f in findings],
        "patches": [dict(row_view(p, patch_keys), changes_count=len(p.get("session_uids") or [])) for p in patches],
        "rpe_mismatch": mismatch,
        "recurring_symptom_sites": sites,
        "open_escalations": sum(
            1
            for f in inputs.exception_findings
            if f.get("status") in NON_TERMINAL_FINDING and f.get("severity") == "escalate"
        ),
    }


def _event_payload(inputs: SnapshotInputs, event: dict | None, day: date, activity_id: Any) -> dict:
    if activity_id is not None:
        candidates = [r for r in inputs.runs if str(r["activity_id"]) == str(activity_id)]
    else:
        candidates = [r for r in inputs.runs if r.get("local_date") is not None and parse_day(r["local_date"]) == day]
    run = max(candidates, key=lambda r: (r.get("distance_m") or 0, str(r["activity_id"])), default=None)
    matched = None
    if run is not None:
        start_at = run.get("start_at")
        matched = {
            "id": run["activity_id"],
            "start_local": parse_instant(start_at).astimezone(ZoneInfo(inputs.timezone)).isoformat()
            if start_at
            else None,
            "distance_m": run.get("distance_m"),
            "duration_s": run.get("timer_s"),
            "rpe": run.get("rpe"),
            "rpe_source": run.get("rpe_source"),
        }
    last = day + timedelta(days=3)
    checkins = [
        {
            **row_view(c, ("observed_at", "kind", "fatigue", "illness", "gait_change", "pain_reported")),
            "symptoms": [
                {"site_key": _site_key(s), "severity": s.get("severity"), "timing": s.get("timing")}
                for s in c.get("symptoms", [])
            ],
        }
        for c in inputs.checkins
        if day_between(c.get("local_date"), day, last)
    ]
    nights = [
        _metric_view(m)
        for m in inputs.metric_results
        if m.get("metric_id") == "recovery_multisignal_summary"
        and m.get("subject_type") == "night"
        and str(m.get("subject_key", "")).startswith("night:")
        and day_between(str(m["subject_key"]).split(":", 1)[1], day - timedelta(days=1), last)
    ]
    return {
        "event": row_view(event, EVENT_KEYS, names={"event_id": "id"}) if event else None,
        "matched_activity": matched,
        "checkins_after": checkins,
        "recovery_nights": nights,
    }


def _event_section(inputs: SnapshotInputs) -> dict | None:
    due = {
        str(f.get("entity_key") or "").removeprefix("event:")
        for f in inputs.exception_findings
        if f.get("rule_code") == "POST_EVENT_REVIEW_DUE" and f.get("status") in NON_TERMINAL_FINDING
    }
    events = [e for e in inputs.events if str(e.get("event_id")) in due]
    if not events:
        return None
    event = max(events, key=lambda e: (str(e.get("event_date")), str(e.get("event_id"))))
    return _event_payload(inputs, event, parse_day(event["event_date"]), None)


def _benchmark_event(inputs: SnapshotInputs) -> dict | None:
    status = (inputs.active_block or {}).get("benchmark_status")
    if not status or status.get("status") != "completed":
        return None
    event = next((e for e in inputs.events if str(e.get("event_id")) == str(status.get("event_id"))), None)
    return _event_payload(inputs, event, parse_day(status["local_date"]), status.get("activity_id"))


def _quality_progression(inputs: SnapshotInputs, operation: str) -> list[dict]:
    cal_start, cal_end = section_window(operation, "calendar", inputs)
    ordered = sorted(inputs.sessions, key=lambda s: (str(s["local_date"]), s.get("slot", 0), str(s["session_uid"])))
    signatures = {str(s["session_uid"]): work_signature(s.get("structure")) for s in ordered if s.get("kind") == "run"}
    wanted = list(
        dict.fromkeys(
            sig
            for s in ordered
            if (sig := signatures.get(str(s["session_uid"]))) and day_between(s.get("local_date"), cal_start, cal_end)
        )
    )[:PROGRESSION_GROUPS_MAX]
    if not wanted:
        return []
    completions = {str(c["session_uid"]): c for c in inputs.completions}
    runs = {str(r["activity_id"]): r for r in inputs.runs}
    intervals = {
        str(m["subject_key"]): m for m in inputs.metric_results if m.get("metric_id") == "work_interval_execution"
    }
    points = []
    for s in ordered:
        if signatures.get(str(s["session_uid"])) not in wanted or parse_day(s["local_date"]) > inputs.as_of:
            continue
        completion = completions.get(str(s["session_uid"]))
        run = runs.get(str(completion["activity_id"])) if completion and completion.get("activity_id") else None
        row = intervals.get(str(run["activity_id"])) if run else None
        points.append(
            session_point(
                {
                    "session_uid": s["session_uid"],
                    "local_date": parse_day(s["local_date"]),
                    "recipe_id": s.get("recipe_id"),
                    "intent": s.get("intent"),
                    "structure": s["structure"],
                },
                completion,
                {"id": run["activity_id"], "local_date": parse_day(run["local_date"]), "sport": run["sport"]}
                if run
                else None,
                {
                    "id": row["result_id"],
                    "status": row["status"],
                    "reason_codes": row["reason_codes"],
                    "value": row["value"],
                }
                if row
                else None,
            )
        )
    groups = {g["signature"]: g for g in assemble_groups(points, "signature")}
    return [
        {
            "signature": sig,
            "recipe_ids": groups[sig]["recipe_ids"],
            "sessions_total": groups[sig]["sessions_total"],
            "sessions_assessable": groups[sig]["sessions_assessable"],
            "recent": [
                row_view(p, PROGRESSION_POINT_KEYS)
                for p in groups[sig]["points"]
                if p["status"] in ("available", "partial")
            ][-PROGRESSION_POINTS_MAX:],
        }
        for sig in wanted
        if sig in groups
    ]


def _aerobic_efficiency(inputs: SnapshotInputs) -> dict:
    rows = {
        str(m["subject_key"]).split(":", 1)[0]: m
        for m in inputs.metric_results
        if m.get("metric_id") == "aerobic_efficiency"
        and m.get("subject_type") == "window"
        and m.get("subject_key") in {f"w28:{inputs.as_of.isoformat()}", f"w84:{inputs.as_of.isoformat()}"}
    }
    section: dict[str, Any] = {"interpretation": "descriptive_only", "recent_runs": []}
    for key in ("w28", "w84"):
        row = rows.get(key)
        if row is None:
            section[key] = None
            continue
        view = _metric_view(row)
        value = dict(view["value"] or {})
        points = value.pop("points", [])
        view["value"] = value
        section[key] = view
        if key == "w84":
            section["recent_runs"] = list(points)[-AEROBIC_RECENT_MAX:]
    return section


def _capped(rows: list[dict], limit: int) -> tuple[list[dict], int]:
    kept = rows[-limit:]
    return kept, len(rows) - len(kept)


def _key_view(row: dict) -> dict:
    actual = row.get("actual") or {}
    execution = row.get("execution") or {}
    return {
        "session_uid": row["session_uid"],
        "local_date": row["local_date"],
        "class": row["class"],
        "recipe_id": row.get("recipe_id"),
        "changed": row["changed"],
        "outcome": row["outcome"],
        "modification_reason": row.get("modification_reason"),
        "planned_duration_s": row.get("planned_duration_s"),
        "planned_distance_m": row.get("planned_distance_m"),
        "actual_duration_s": actual.get("duration_s"),
        "actual_distance_m": actual.get("distance_m"),
        "sport": actual.get("sport"),
        "avg_hr_bpm": actual.get("avg_hr_bpm"),
        "moving_pace_s_per_km": actual.get("moving_pace_s_per_km"),
        "rpe": actual.get("rpe"),
        "activity_id": actual.get("id") if actual.get("subject") == "activity" else None,
        "assessment_status": execution.get("assessment_status"),
        "reason_codes": list(execution.get("reason_codes") or []),
        "quality_flags": list(execution.get("quality_flags") or []),
        "components": [dict(c) for c in execution.get("components") or []],
        "reps_planned": execution.get("reps_planned"),
        "reps_completed": execution.get("reps_completed"),
    }


def _digest_week_view(week: dict) -> dict:
    rows = sorted(
        week.get("sessions") or [], key=lambda r: (str(r["local_date"]), r.get("slot") or 0, str(r["session_uid"]))
    )
    key, key_omitted = _capped([_key_view(r) for r in rows if r["key"]], KEY_SESSIONS_MAX)
    not_done, not_done_omitted = _capped(
        [
            {
                "session_uid": r["session_uid"],
                "local_date": r["local_date"],
                "kind": r["kind"],
                "class": r["class"],
                "outcome": r["outcome"],
            }
            for r in rows
            if not r["key"] and r["kind"] in HEADLINE_KINDS and r["outcome"] in NOT_DONE_OUTCOMES
        ],
        NOT_DONE_MAX,
    )
    unplanned, unplanned_omitted = _capped(
        [dict(u) for u in sorted(week.get("unplanned") or [], key=lambda u: (str(u["local_date"]), str(u["id"])))],
        UNPLANNED_MAX,
    )
    return {
        "week_start": week["week_start"],
        "week_end": week["week_end"],
        "days_elapsed": week["days_elapsed"],
        "activity_coverage_complete": week["activity_coverage_complete"],
        "totals": week["totals"],
        "decision_follow_up": week.get("decision_follow_up"),
        "rehab_sessions": [
            {
                "session_uid": r["session_uid"],
                "local_date": r["local_date"],
                "slot": r["slot"],
                "intent": r["intent"],
                "planned_duration_s": r["planned_duration_s"],
                "outcome": r["outcome"],
            }
            for r in rows
            if r["kind"] == "rehab"
        ],
        "key_sessions": key,
        "key_sessions_omitted": key_omitted,
        "not_done": not_done,
        "not_done_omitted": not_done_omitted,
        "unplanned": unplanned,
        "unplanned_omitted": unplanned_omitted,
    }


def _weekly_digest_view(inputs: SnapshotInputs) -> dict:
    return {
        "schema": DIGEST_SCHEMA,
        "timezone": inputs.timezone,
        "weeks": [_digest_week_view(w) for w in inputs.weekly_digest],
    }


TRAVEL_TRIPS_MAX = 8
NIGHT_START = time(23)
NIGHT_END = time(6)


def _hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


def _half_hours(value: float) -> float:
    return math.floor(value * 2 + 0.5) / 2


def _night_overlap(dep: datetime, arr: datetime, zone: ZoneInfo) -> bool:
    start, end = dep.astimezone(zone), arr.astimezone(zone)
    day = start.date() - timedelta(days=1)
    while day <= end.date():
        night_start = datetime.combine(day, NIGHT_START, zone)
        night_end = datetime.combine(day + timedelta(days=1), NIGHT_END, zone)
        if start < night_end and end > night_start:
            return True
        day += timedelta(days=1)
    return False


def _offset(instant: datetime) -> timedelta:
    offset = instant.utcoffset()
    if offset is None:
        raise ValueError("Trip times require a UTC offset")
    return offset


def _leg_view(leg: dict) -> dict:
    dep, arr = parse_instant(leg["depart_local"]), parse_instant(leg["arrive_local"])
    known = leg.get("timezone_basis") == "calendar_endpoints"
    return {
        **leg,
        "duration_hours": _half_hours(_hours(arr - dep)),
        "zone_shift_hours": _hours(_offset(arr) - _offset(dep)) if known else None,
        "night_overlap": _night_overlap(dep, arr, ZoneInfo(leg["depart_timezone"])) if known else None,
    }


def _trip_shift(start: date, destination: str, home: ZoneInfo) -> float:
    noon = datetime.combine(start, time(12), home)
    shift = _hours(_offset(noon.astimezone(ZoneInfo(destination))) - _offset(noon))
    while shift > 12:
        shift -= 24
    while shift <= -12:
        shift += 24
    return shift


def _trip_view(trip: dict, home: ZoneInfo) -> dict:
    start = parse_day(trip["start_date"])
    legs = trip.get("legs", [])
    # Pending itineraries can carry Google's display zone as a provisional destination.
    known = (
        trip["confirmed"]
        or trip["source"] == "manual"
        or (bool(legs) and all(leg.get("timezone_basis") == "calendar_endpoints" for leg in legs))
    )
    shift = _trip_shift(start, trip["destination_timezone"], home) if known else None
    end = trip.get("end_date")
    return {
        **trip,
        "zone_shift_hours": shift,
        "direction": None if shift is None else "east" if shift > 0 else "west" if shift < 0 else "none",
        "nights_away": (parse_day(end) - start).days if end else None,
        "legs": [_leg_view(leg) for leg in trip.get("legs", [])],
    }


def _travel_section(inputs: SnapshotInputs) -> dict:
    home_name = inputs.travel_meta.get("home_timezone") or inputs.timezone
    trips = sorted(inputs.trips, key=lambda t: (str(t["start_date"]), str(t["trip_id"])))
    kept = trips[:TRAVEL_TRIPS_MAX]
    return {
        "home_timezone": home_name,
        "calendar_synced_at": inputs.travel_meta.get("calendar_synced_at"),
        "trips": [_trip_view(t, ZoneInfo(home_name)) for t in kept],
        "trips_omitted": len(trips) - len(kept),
    }


def build_payload(inputs: SnapshotInputs, operation: str) -> dict:
    if operation not in OPERATIONS:
        raise ValueError("unsupported_operation")
    review_date = active_review_date(inputs)
    start, end = scope(operation, inputs.as_of, review_date)
    if operation in {BLOCK, RACE}:
        end = inputs.as_of + timedelta(days=HORIZON_MAX_DAYS)
    payload: dict[str, Any] = {
        "snapshot_meta": {
            "schema_version": SNAPSHOT_SCHEMA,
            "operation": operation,
            "as_of": inputs.as_of,
            "timezone": inputs.timezone,
            "calendar_version": inputs.calendar_version,
            "block_version_id": inputs.active_block.get("version_id") if inputs.active_block else None,
            "data_revision": inputs.data_revision,
            "scope": {"start": start, "end": end},
            "safety_guard": _safety_guard(inputs),
        },
        "completed_exposures": _completed_exposures(inputs, operation),
        "anchors": [
            row_view(
                a,
                (
                    "anchor_key",
                    "kind",
                    "value_low",
                    "value_high",
                    "unit",
                    "protocol",
                    "confidence",
                    "status",
                    "calibrated_at",
                    "valid_from",
                    "review_after",
                    "supersedes_key",
                ),
            )
            for a in inputs.anchors
            if operation in {BLOCK, CALIB} or a.get("status") == "active"
        ],
        "data_quality": _data_quality(inputs),
        "drill_down_queries": list(DRILL_DOWN_QUERIES),
    }
    if inputs.running_interruption is not None:
        interruption = dict(inputs.running_interruption)
        for key in ("affected_runs",):
            interruption[key] = [{k: v for k, v in row.items() if k != "intent"} for row in interruption.get(key, [])]
        if interruption.get("first_run"):
            interruption["first_run"] = {k: v for k, v in interruption["first_run"].items() if k != "intent"}
        payload["running_interruption"] = interruption
    if inputs.running_restriction is not None:
        payload["snapshot_meta"]["running_restriction"] = inputs.running_restriction
    if operation in HORIZON_OPS:
        payload["snapshot_meta"]["horizon"] = {
            "min_end": inputs.as_of + timedelta(days=HORIZON_MIN_DAYS),
            "max_end": inputs.as_of + timedelta(days=HORIZON_MAX_DAYS),
            "rule": "active_block_review_date" if operation == ROLLING else "proposed_block_review_date",
            "block_review_due": review_date is not None
            and review_date <= inputs.as_of + timedelta(days=BLOCK_REVIEW_LEAD_DAYS),
        }
    if operation != CALIB:
        goals = [row_view(g, ("goal_id", "text", "horizon", "priority", "status")) for g in inputs.goals]
        events = [row_view(e, EVENT_KEYS) for e in inputs.events]
        slots = [
            row_view(
                s,
                (
                    "slot_id",
                    "label",
                    "default_weekday",
                    "lower_body_cost",
                    "typical_duration_s",
                    "main_lower_body_lifts",
                ),
            )
            for s in inputs.strength_slots
            if s.get("active", True)
        ]
        latest = sorted(inputs.strong_workouts, key=lambda s: str(s["local_date"]), reverse=True)[:2]
        goals_view = {
            "strength_routine": slots,
            "latest_strong_sessions": [row_view(s, ("local_date", "workout_name", "duration_s")) for s in latest],
            "run_cycle": {"anchor_date": inputs.cycle_anchor, "confirmed": inputs.anchor_confirmed},
            "clinical_restriction": inputs.clinical_restriction,
        }
        if operation in HORIZON_OPS or inputs.accepted_strength_omissions:
            goals_view["confirmed_strength_sessions"] = [
                row for row in inputs.confirmed_strength_sessions if day_between(row["local_date"], start, end)
            ]
            goals_view["accepted_strength_omissions"] = [
                row for row in inputs.accepted_strength_omissions if day_between(row["local_date"], start, end)
            ]
        if operation not in {DAILY, EXCEPTION}:
            top = next((e for e in events if e["rank"] == 1), None)
            goal_race = (
                {"event_id": top["event_id"], "days_until": (parse_day(top["event_date"]) - inputs.as_of).days}
                if top
                else None
            )
            goals_view.update(goals=goals, events=events, goal_race=goal_race)
        payload["goals_and_constraints"] = goals_view
        cal_start, cal_end = section_window(operation, "calendar", inputs)
        completions = {str(c["session_uid"]): c for c in inputs.completions}
        sessions = [
            _session_view(s, completions.get(str(s["session_uid"])))
            for s in inputs.sessions
            if day_between(s.get("local_date"), cal_start, cal_end)
        ]
        sessions.sort(key=lambda s: (str(s["local_date"]), s["slot"], str(s["session_uid"])))
        payload["calendar"] = {
            "head": inputs.calendar_version,
            "start": cal_start,
            "end": cal_end,
            "sessions": sessions,
        }
    block = inputs.active_block
    if operation == BLOCK:
        payload["block"] = {
            "active": row_view(block, tuple(block)) if block else None,
            "history": _prior_decisions(inputs, BLOCK),
        }
    elif operation in {DAILY, EXCEPTION}:
        payload["block"] = (
            row_view(block, ("block_uid", "version_id", "objective", "benchmark", "benchmark_status"))
            if block
            else None
        )
    elif operation == CALIB:
        payload["block"] = (
            {
                "objective": block["objective"],
                "benchmark": block.get("benchmark"),
                "benchmark_status": block.get("benchmark_status"),
            }
            if block
            else None
        )
    else:
        payload["block"] = row_view(block, tuple(block)) if block else None
    if operation not in {CALIB}:
        windows = [7] if operation in {DAILY, EXCEPTION} else [7, 14, 28, 56, 84] if operation == BLOCK else [7, 14, 28]
        keys = {f"w{days}:{inputs.as_of.isoformat()}" for days in windows}
        keys.update(f"w{days}:{inputs.as_of.isoformat()}:{kind}" for days in windows for kind in ("run", "strength"))
        payload["load_shape"] = [
            _metric_view(m)
            for m in inputs.metric_results
            if m.get("subject_type") == "window"
            and m.get("subject_key") in keys
            and m.get("metric_id") != "aerobic_efficiency"
        ]
    if operation not in {RACE}:
        quality_runs = [r for r in payload["completed_exposures"]["runs"] if r["class"] == "quality"]
        if operation in {DAILY, EXCEPTION}:
            quality_runs = quality_runs[-1:]
        exposure_ids = {str(r["activity_id"]) for r in quality_runs}
        execution = [
            _metric_view(m)
            for m in inputs.metric_results
            if m.get("metric_id") == "work_interval_execution" and str(m.get("subject_key")) in exposure_ids
        ]
        payload["execution"] = execution
    if operation in {ROLLING, QUALITY_OP, BLOCK}:
        payload["quality_progression"] = _quality_progression(inputs, operation)
    if operation in {ROLLING, BLOCK}:
        payload["aerobic_efficiency"] = _aerobic_efficiency(inputs)
    if operation not in {CALIB}:
        payload["symptoms"] = _symptoms(inputs, operation)
    if operation in {DAILY, ROLLING, QUALITY_OP, BLOCK, EXCEPTION, POST_EVENT}:
        rec_start, rec_end = section_window(operation, "recovery", inputs)
        payload["recovery"] = [
            _metric_view(m)
            for m in inputs.metric_results
            if m.get("metric_id") == "recovery_multisignal_summary"
            and m.get("subject_type") == "night"
            and str(m.get("subject_key", "")).startswith("night:")
            and day_between(str(m["subject_key"]).split(":", 1)[1], rec_start, rec_end)
        ]
    if operation in {DAILY, ROLLING, QUALITY_OP, BLOCK, CALIB, EXCEPTION, POST_EVENT}:
        payload["prior_decisions"] = _prior_decisions(inputs, operation)
    if operation in {EXCEPTION, POST_EVENT}:
        payload["exceptions"] = _exceptions_section(inputs)
    if operation in {ROLLING, BLOCK}:
        payload["exception_summary"] = _exception_summary(inputs)
        payload["weekly_digest"] = _weekly_digest_view(inputs)
    if operation == POST_EVENT:
        payload["event"] = _event_section(inputs)
    if operation == BLOCK:
        payload["benchmark_history"] = list(inputs.benchmark_history)
        if (benchmark_event := _benchmark_event(inputs)) is not None:
            payload["event"] = benchmark_event
    if operation != CALIB:
        payload["travel"] = _travel_section(inputs)
    return strip_private(to_wire(payload))
