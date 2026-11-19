"""Exception detector vocabulary (exceptions.v1)."""

from __future__ import annotations

from typing import Literal, get_args

Category = Literal["symptoms_illness", "training_response", "accumulated_fatigue", "calendar_disruption", "post_event"]
PatchCategory = Literal["symptoms_illness", "training_response", "accumulated_fatigue", "calendar_disruption"]
Severity = Literal["observe", "caution", "hold", "escalate"]
FindingStatus = Literal["open", "addressed", "reviewed", "resolved", "dismissed", "expired"]
PatchStatus = Literal["open", "resolved", "escalated", "superseded"]
LadderLevel = Literal["current_session", "next_session", "next_days", "committed_window", "block"]

CATEGORY: tuple[Category, ...] = get_args(Category)
PATCH_CATEGORY: tuple[PatchCategory, ...] = get_args(PatchCategory)
SEVERITY: tuple[Severity, ...] = get_args(Severity)
FINDING_STATUS: tuple[FindingStatus, ...] = get_args(FindingStatus)
NON_TERMINAL_FINDING: tuple[FindingStatus, ...] = ("open", "addressed")
TERMINAL_FINDING: tuple[FindingStatus, ...] = ("reviewed", "resolved", "dismissed", "expired")
PATCH_STATUS: tuple[PatchStatus, ...] = get_args(PatchStatus)
LADDER: tuple[LadderLevel, ...] = get_args(LadderLevel)
RULE_VERSION = "exceptions.v1"


def severity_rank(severity: Severity) -> int:
    return SEVERITY.index(severity)


def max_severity(first: Severity, *others: Severity) -> Severity:
    return max((first, *others), key=severity_rank)
