from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder

ENGINE = "local_rules.v1"
EVIDENCE = {
    "P001": ["E-REC-04", "E-WEAR-05"],
    "P002": ["E-REC-01", "E-WEAR-02", "E-WEAR-05"],
    "P003": ["E-REC-02", "E-REC-03", "E-REC-04"],
    "P004": ["E-AER-05", "E-AER-06"],
    "P005": ["E-PTT-02", "E-PTT-04", "E-WEAR-05"],
    "P006": ["E-PTT-02", "E-PTT-06"],
    "P007": ["E-AER-03", "E-PTT-02"],
    "P008": ["E-PTT-06"],
    "P009": ["E-AER-03", "E-AER-05"],
    "P010": ["E-INT-04", "E-DATA-01", "E-DATA-02"],
    "P011": ["E-HYB-01"],
    "P012": ["E-HYB-01", "E-HYB-04"],
    "P013": ["E-AER-03", "E-AER-05"],
    "P014": ["E-AER-01", "E-AER-02"],
    "P015": ["E-WEAR-04", "E-DATA-02"],
    "P016": ["E-LONG-03"],
    "P017": ["E-FUEL-01"],
    "P018": ["E-PTT-02", "E-PTT-04"],
}


def fingerprint(value: Any) -> str:
    return sha256(json.dumps(jsonable_encoder(value), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def references(ids: list[str]) -> dict:
    return {"policy_ids": ids, "evidence_ids": sorted({e for p in ids for e in EVIDENCE[p]})}


def _date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _instant(value: Any) -> datetime:
    return (value if isinstance(value, datetime) else datetime.fromisoformat(str(value))).astimezone(UTC)


def _current_checkin(context: dict, as_of: date) -> tuple[dict | None, bool]:
    zone = ZoneInfo(context.get("timezone") or "America/New_York")
    rows = [
        r for r in context.get("recent_checkins", []) if _instant(r["observed_at"]).astimezone(zone).date() <= as_of
    ]
    rows.sort(key=lambda r: str(r["observed_at"]), reverse=True)
    row = rows[0] if rows else None
    return row, bool(row and _instant(row["observed_at"]).astimezone(zone).date() == as_of)


def _planned(context: dict, as_of: date) -> dict | None:
    plans = context.get("next_14_days_plan", [])
    plans = sorted(plans, key=lambda p: (str(p.get("decided_at") or ""), p.get("version", 0)), reverse=True)
    for plan in plans:
        for session in plan.get("sessions", []):
            if _date(session["date"]) == as_of:
                return session
    return None


def _run_day(context: dict, as_of: date) -> bool | None:
    profile = context.get("profile", {})
    if not profile.get("anchor_confirmed") or not profile.get("cycle_anchor"):
        return None
    return (as_of - _date(profile["cycle_anchor"])).days % 2 == 0


def _session(mode: str, purpose: str, structure: str, intensity: str, terrain: str | None = None) -> dict:
    return {
        "mode": mode,
        "purpose": purpose,
        "duration_or_structure": structure,
        "intensity_instruction": intensity,
        "terrain_or_equipment": terrain,
    }


def daily(context: dict, as_of: date, supplemental: dict, *, today: date) -> dict:
    checkin, same_day = _current_checkin(context, as_of)
    if checkin and same_day:
        checkin_time = _instant(checkin["observed_at"])
        # A pre-session check-in cannot certify the response to a later run or lift.
        if any(
            not a.get("start_at") or a.get("elapsed_s") is None or (
                _instant(a["start_at"]) + timedelta(seconds=a.get("elapsed_s") or 0)
            ) > checkin_time
            for a in context.get("recent_activities", [])
            if _date(a["local_date"]) == as_of
            and a.get("sport") in {"running", "trail_running", "treadmill_running", "strength"}
        ):
            same_day = False
    planned = _planned(context, as_of)
    run_day = _run_day(context, as_of)
    kind = (
        planned["kind"]
        if planned
        else ("run" if run_day else "strength_or_mobility" if run_day is False else "unscheduled")
    )
    target = planned.get("target") or {} if planned else {}
    intent = str(
        target.get("intent") or target.get("workout_label") or target.get("type") or ("easy" if kind == "run" else kind)
    ).lower()
    if intent not in {"easy", "quality", "long"} and kind == "run":
        intent = "easy"
    illness = supplemental.get("illness", "unknown")
    soreness = supplemental.get("lower_body_soreness", "unknown")
    restriction = supplemental.get("clinician_restriction", "unknown")
    symptoms = checkin.get("symptoms") if same_day and checkin else None
    change = checkin.get("change") if same_day and checkin else None
    gait = checkin.get("gait") if same_day and checkin else None
    feeling = checkin.get("feeling") if same_day and checkin else None
    missing = []
    if as_of > today:
        missing.append("Future-day symptoms and illness require a fresh check-in before starting.")
        symptoms = change = gait = feeling = None
    elif not same_day:
        missing.append("No current-day symptom and gait check-in; prior feedback is historical.")
    if gait == "unsure":
        missing.append("Current walking/gait effect is uncertain; confirm movement before training.")
    if illness == "unknown":
        missing.append("Current illness state unknown.")
    if restriction == "unknown":
        missing.append("Current clinician restrictions unknown.")
    if soreness == "unknown":
        missing.append("Current lower-body soreness unknown.")
    if run_day is None:
        missing.append("Run-cycle anchor is not confirmed; today cannot be certified as a run day.")
    if not context.get("recovery", {}).get("series", {}).get("hrv"):
        missing.append("HRV unavailable; no recovery state inferred from it.")
    if not planned:
        missing.append("No accepted session for this date; session is provisional.")
    ids: list[str] = ["P001"] if missing else []
    decision = "proceed"
    reason = "Keep the planned exposure familiar and check effort and symptoms during warm-up."
    change_plan = "None; no plan edit is made."
    if kind == "run":
        proposed = _session(
            "run",
            f"{intent} aerobic session",
            "Use the accepted plan structure if present; otherwise choose a familiar, previously tolerated easy duration.",
            "Conversational easy effort; use perceived effort rather than a derived pace or heart-rate zone.",
            "Familiar, even terrain",
        )
        fallback = _session(
            "rest_or_low_impact",
            "Preserve recovery",
            "Rest or a previously tolerated low-impact aerobic option.",
            "Easy and symptom-limited; no running-mile equivalent.",
            None,
        )
    elif kind == "strength":
        proposed = _session(
            "strength",
            "Preserve full-body strength",
            "Use the familiar planned full-body session; adjust provocative lower-body work if needed.",
            "Controlled effort, with normal movement quality.",
            "Familiar exercises",
        )
        fallback = _session(
            "strength_modified",
            "Preserve the strength routine",
            "Keep comfortable upper-body and non-provocative work; defer provocative lower-body work.",
            "Comfortable effort.",
            None,
        )
        ids.append("P011")
    elif kind == "mobility":
        proposed = _session(
            "mobility",
            "Maintain mobility routine",
            "Use the familiar mobility session.",
            "Comfortable, non-provocative movement.",
        )
        fallback = _session("rest", "Recover", "Rest and reassess symptoms.", "No exercise target.")
    else:
        proposed = _session(
            "rest_or_familiar_activity",
            "Maintain the cycle without adding a run",
            "Rest, or use a familiar strength/mobility session if already scheduled.",
            "Comfortable effort.",
        )
        fallback = _session("rest", "Recover", "Rest and reassess.", "No exercise target.")
    if restriction == "restricted":
        decision, reason, ids = (
            "seek_clinical_input",
            "Follow the current clinician restriction and clarify allowed activity before training.",
            ["P018"],
        )
        proposed = _session(
            "rest",
            "Respect clinician restriction",
            "Do not start a session that conflicts with the restriction.",
            "No exercise target.",
        )
    elif illness == "systemic":
        decision, reason, ids = (
            "seek_clinical_input",
            "Systemic illness symptoms need clinical guidance before resuming training.",
            ["P004", "P018"],
        )
        proposed = _session(
            "rest",
            "Recover from illness",
            "Rest; seek clinical advice for fever, chest symptoms, unusual breathlessness, palpitations, or worsening illness.",
            "No exercise target.",
        )
    elif gait == "affected" or (symptoms in {"moderate", "severe"} and change == "worse"):
        decision, reason, ids = (
            "seek_clinical_input",
            "Changed walking or worsening function takes priority over wearable scores and the planned session.",
            ["P005", "P018"],
        )
        proposed = _session(
            "rest",
            "Protect walking function",
            "Skip the planned run; seek clinical assessment if symptoms are progressive or function limiting.",
            "No exercise target.",
        )
    elif change == "worse" or symptoms in {"moderate", "severe"}:
        decision, reason, ids = (
            "modify",
            "Current tendon symptoms warrant a smaller, familiar exposure and delayed reassessment.",
            ["P005", "P006", "P008"],
        )
        proposed = _session(
            "rest_or_tolerated_low_impact",
            "Avoid provoking symptoms",
            "Rest or use a previously tolerated low-impact option only if comfortable.",
            "Easy and symptom-limited.",
        )
    elif illness == "mild":
        decision, reason, ids = (
            "modify",
            "Mild illness alone does not establish that symptoms are resolving or rule out systemic warning signs; check these before exercising.",
            ["P001", "P004", "P013"],
        )
        proposed = _session(
            "conditional_easy_challenge",
            "Check whether return to exercise is appropriate",
            "Rest now; if symptoms are clearly resolving and there is no fever, chest pain, palpitations, unusual breathlessness, or clinician restriction, consider a brief familiar easy effort. Stop if symptoms worsen.",
            "Easy; monitor during, immediately after, and next day.",
        )
    elif soreness == "affects_movement":
        decision, reason, ids = (
            "modify",
            "Lower-body soreness is changing movement; defer quality and reassess after an easy warm-up.",
            ["P011", "P012"],
        )
        if kind == "strength":
            proposed = _session("strength_modified", "Preserve the strength routine", "Use comfortable upper-body and non-provocative work only; defer lower-body loading until movement normalizes.", "Comfortable, symptom-limited effort.")
        elif kind == "mobility":
            proposed = _session("mobility_modified", "Keep comfortable mobility", "Use only movements that do not change gait or provoke symptoms; otherwise rest.", "Comfortable effort.")
        elif kind == "run":
            proposed = _session("easy_or_rest", "Preserve movement quality", "Short familiar easy run only if gait normalizes; otherwise rest or tolerated low-impact work.", "Easy, no pace target.")
        else:
            proposed = _session("rest", "Preserve movement quality", "Rest and reassess before choosing any activity.", "No exercise target.")
    elif kind == "run" and intent in {"quality", "long"} and (feeling == "tired" or symptoms == "mild" or not same_day):
        decision, reason, ids = (
            "modify",
            "A demanding run needs a current symptom and fatigue check; use an easy fallback today.",
            ["P001"],
        )
        proposed = _session(
            "easy_run",
            "Maintain the run opportunity",
            "Use a familiar easy duration; do not add a make-up quality or long run.",
            "Conversational effort, no pace target.",
            "Familiar even terrain",
        )
    elif feeling == "tired" and kind == "run":
        decision, reason, ids = (
            "modify",
            "Subjective fatigue supports a lower-demand version of today’s run; one tired day does not establish a recovery trend.",
            ["P001"],
        )
        proposed = _session(
            "easy_run",
            "Maintain continuity",
            "Familiar easy duration; shorten if warm-up effort is unusually high.",
            "Conversational effort.",
        )
    elif kind == "run" and not same_day:
        decision, reason, ids = (
            "modify",
            "Current symptoms are unknown; this is a conditional easy option, not clearance to run.",
            ["P001"],
        )
        proposed = _session(
            "conditional_easy_run",
            "Maintain the run opportunity if the quick check is reassuring",
            "First check current tendon symptoms, gait, illness, and restrictions; then choose a familiar easy duration or rest.",
            "Conversational effort, no pace target.",
            "Familiar even terrain",
        )
    if decision == "seek_clinical_input":
        fallback = _session("rest", "Respect current safety limits", "Rest until current restrictions and symptoms are clarified.", "No exercise target.")
    if soreness == "unknown" and decision == "proceed":
        decision = "modify"
        reason = "Current lower-body soreness is unknown; check movement quality before this session."
        ids = ["P001", "P011"]
        proposed = _session("conditional_familiar_activity", "Check movement before training", "If walking and warm-up movement are normal, use the familiar planned session; otherwise rest or choose a non-provocative option.", "Comfortable, symptom-limited effort.")
    if run_day is None and not planned and decision == "proceed":
        decision = "modify"
        reason = "Confirm the continuous every-other-day run anchor before assigning a run to this date."
        ids = ["P001", "P013"]
    if as_of > today and decision == "proceed":
        decision = "modify"
        reason = "Tomorrow’s option is provisional until tomorrow’s symptom, gait, and illness check."
        ids = ["P001"]
    if decision == "proceed" and (not same_day or gait == "unsure" or illness == "unknown" or restriction == "unknown"):
        decision = "modify"
        reason = (
            "This session is conditional until current symptoms, gait, illness, and clinician restrictions are checked."
        )
        ids = ["P001"]
        proposed = _session(
            "conditional_familiar_activity",
            "Keep the planned routine only if the quick check is reassuring",
            "Check current symptoms, walking, illness, and restrictions first; then use the familiar planned session or rest.",
            "Comfortable, symptom-limited effort.",
        )
    ids = list(dict.fromkeys(ids))
    return {
        "decision": decision,
        "planned_session": {
            "kind": kind,
            "intent": intent,
            "target": target,
            "id": str(planned["id"]) if planned else None,
        },
        "proposed_session": proposed,
        "alternative": fallback,
        "change_from_plan": change_plan if decision == "proceed" else reason,
        "short_rationale": reason,
        "references": references(ids),
        "confidence": {
            "evidence": "low" if "P018" in ids else "moderate",
            "athlete_applicability": "moderate" if same_day else "low",
            "decision": "low" if missing or run_day is None else "moderate",
        },
        "missing_or_stale_inputs": missing,
        "follow_up_observation": {
            "what": "Recheck tendon symptoms and walking, including delayed response after a run; note unusual effort or illness change.",
            "when": "During and after the session, then again 16–40 hours later after running.",
        },
        "audit": {
            "data_through": str(context.get("generated_at")),
            "proposed_changes": [],
            "engine_scope": "Evidence-guided local decision support; no diagnosis, plan write, or trained personalization.",
        },
    }


def weekly(context: dict, as_of: date) -> dict:
    start = as_of - timedelta(days=13)
    rows = [a for a in context.get("recent_activities", []) if start <= _date(a["local_date"]) <= as_of]
    runs = [a for a in rows if a.get("sport") in {"running", "trail_running", "treadmill_running"}]
    strengths = [a for a in rows if a.get("sport") == "strength"]
    zone = ZoneInfo(context.get("timezone") or "America/New_York")
    checkins = [
        c for c in context.get("recent_checkins", [])
        if start <= _instant(c["observed_at"]).astimezone(zone).date() <= as_of
    ]
    checkins.sort(key=lambda c: str(c["observed_at"]), reverse=True)
    latest = checkins[0] if checkins else None
    worsening = bool(latest and (latest.get("change") == "worse" or latest.get("gait") == "affected"))
    earlier_worse = any(c.get("change") == "worse" or c.get("gait") == "affected" for c in checkins[1:])
    delayed_worse = [
        c for c in checkins
        if (c.get("change") == "worse" or c.get("gait") == "affected")
        and any(
            a.get("kind") in {"running", "trail_running", "treadmill_running"}
            and a.get("elapsed_hours") is not None
            and 16 <= a["elapsed_hours"] <= 40
            for a in c.get("associations", [])
        )
    ]
    plan_sessions = [
        s
        for p in context.get("recent_14_days_plan", [])
        for s in p.get("sessions", [])
        if start <= _date(s["date"]) <= as_of
    ]
    completed = sum(bool(s.get("completion_link_id")) for s in plan_sessions)
    unlinked = sum(not s.get("completion_link_id") for s in plan_sessions)
    unknown = []
    if not context.get("profile", {}).get("anchor_confirmed"):
        unknown.append("Run-cycle anchor is unconfirmed; do not assign exact future run dates.")
    if not checkins:
        unknown.append("No symptom feedback in this 14-day review; tolerance is unknown.")
    elif earlier_worse and not worsening:
        unknown.append(
            "Earlier worsening was followed by a more recent report without worsening; confirm delayed response before treating it as resolved."
        )
    if not plan_sessions:
        unknown.append("No accepted plan for an actual-versus-planned comparison.")
    elif unlinked:
        unknown.append(
            f"{unlinked} planned sessions lack a confirmed completion link; they are not classified as missed."
        )
    if not strengths:
        unknown.append("No strength completion is visible; manual or Garmin coverage may be incomplete.")
    if not context.get("recovery", {}).get("series", {}).get("hrv"):
        unknown.append("HRV absent; no recovery trend inferred.")
    target = "reduce mechanical load while preserving aerobic work" if worsening else "consolidate continuity"
    concern = ["Worsening symptoms or affected gait reported; avoid increasing running demands."] if worsening else []
    ids = ["P005", "P006", "P007"] if worsening else ["P007", "P009", "P013", "P014"]
    if unknown:
        ids.append("P001")
    metrics = context.get("last_14_days", {})
    rolling = metrics.get("rolling_14", {})
    rolling_7 = metrics.get("rolling_7", {})
    longest = rolling.get("longest_elapsed_s")
    volume = {
        "rolling_7_km": round((rolling_7.get("distance_m") or 0) / 1000, 2),
        "rolling_14_km": round((rolling.get("distance_m") or 0) / 1000, 2),
        "longest_run_minutes": round(longest / 60, 1) if longest is not None else None,
        "missing_distance_count": rolling.get("missing_distance_count", 0),
    }
    return {
        "period_reviewed": {"start": start.isoformat(), "end": as_of.isoformat(), "primary_horizon": "rolling_14_days"},
        "observed_training": volume,
        "actual_vs_planned": {
            "summary": f"{len(runs)} recorded runs and {len(strengths)} recorded strength sessions in the last 14 days. "
            + ("Plan completion is partly known." if plan_sessions else "No accepted plan comparison is available."),
            "completed_as_planned": completed if plan_sessions else None,
            "modified": None,
            "missed": None,
            "key_differences": [
                "Unlinked plan items remain unknown, not missed. Do not make up missed sessions by compressing exposures."
            ]
            if unlinked
            else [],
        },
        "adaptation_signals": ["No comparable-effort fitness inference is available from these summaries."],
        "tolerance_signals": {
            "favorable": [],
            "concerning": concern,
            "delayed_symptom_findings": [
                f"{len(delayed_worse)} worsening check-in(s) occurred 16–40 hours after a recorded run; timing is an association, not proof of cause."
            ] if delayed_worse else ["Check 16–40-hour response after longer runs; current entries do not establish causality."],
        },
        "strength_running_interactions": [
            f"{len(strengths)} strength sessions recorded; preserve the twice-weekly intent and review placement near demanding runs."
        ],
        "confounders_and_data_quality": unknown
        + [
            "Pace and heart-rate changes are not interpreted without comparable route, weather, effort, and sensor quality."
        ],
        "prior_advice_outcomes": [
            f"{o['as_of']}: {o['kind']} advice {o['status']}; reported effect {o['effect'] or 'unknown'}."
            for o in context.get("prior_coaching_outcomes", [])
        ]
        or ["No explicit recommendation outcome was recorded in this period."],
        "next_cycle_proposal": {
            "primary_target": target,
            "sessions_or_placement_principles": [
                "Keep every-other-day running on the continuous cycle; confirm its anchor before assigning exact dates.",
                "Keep one quality and one long-run intent weekly only when symptoms and recovery support them.",
                "Preserve the intended twice-weekly full-body strength; confirm its placement against the current schedule.",
            ],
            "changes_from_current_plan": [
                "Hold long-run and quality progression pending stable delayed symptom response."
            ]
            if worsening
            else ["Consolidate the present structure; do not increase volume and intensity together."],
            "preserved_commitments": ["Every-other-day running", "Two strength sessions weekly"],
        },
        "tradeoffs": ["Maintaining continuity may be more useful than adding load while symptom response is unclear."],
        "references": references(list(dict.fromkeys(ids))),
        "uncertainties": unknown,
        "what_would_change_the_recommendation": [
            "Current check-in and delayed response after the next long run.",
            "Comparable easy-run effort and completed strength placement.",
        ],
        "audit": {
            "data_through": str(context.get("generated_at")),
            "engine_scope": "Evidence-guided local decision support; no automatic plan edit.",
        },
    }
