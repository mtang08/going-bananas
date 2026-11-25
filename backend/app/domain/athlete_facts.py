"""Readers for athlete profile facts."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

CLINICAL_RESTRICTION_KEY = "clinical_restriction"
LEGACY_RESTRICTION_TEXT_KEY = "clinician_restriction"
LEGACY_RESTRICTION_FLAG_KEY = "clinical_restriction_active"
_EMPTY = frozenset({"", "none", "unknown"})


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return None if text.casefold() in _EMPTY else text


def clinical_restriction(facts: dict[str, Any] | None) -> str | None:
    facts = facts or {}
    for key in (CLINICAL_RESTRICTION_KEY, LEGACY_RESTRICTION_TEXT_KEY):
        if (text := _text(facts.get(key))) is not None:
            return text
    return "restricted" if facts.get(LEGACY_RESTRICTION_FLAG_KEY) else None


RUNNING_RESTRICTION_KEY = "running_restriction"


class RunningRestriction(BaseModel):
    """A manually confirmed prescription constraint, with inclusive date bounds."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    starts_on: date
    ends_on: date | None = None
    review_on: date | None = None
    pause_running: bool = False
    no_quality: bool = False
    max_distance_m: int | None = Field(default=None, strict=True, gt=0)
    max_duration_s: int | None = Field(default=None, strict=True, gt=0)
    source: str = Field(min_length=1, max_length=120)
    wording: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def valid_limits(self) -> RunningRestriction:
        if self.ends_on is not None and self.ends_on < self.starts_on:
            raise ValueError("Last restricted day cannot be before the start")
        if self.review_on is not None and self.review_on < self.starts_on:
            raise ValueError("Review date cannot be before the start")
        if not (self.pause_running or self.no_quality or self.max_distance_m or self.max_duration_s):
            raise ValueError("Enter at least one running limit")
        return self

    def applies_on(self, day: date) -> bool:
        return day >= self.starts_on and (self.ends_on is None or day <= self.ends_on)

    def snapshot_data(self, today: date) -> dict[str, Any]:
        return {
            **self.model_dump(mode="json"),
            "needs_confirmation": self.ends_on is None and self.review_on is not None and today >= self.review_on,
        }


def running_restriction(facts: dict[str, Any] | None) -> RunningRestriction | None:
    raw = (facts or {}).get(RUNNING_RESTRICTION_KEY)
    return RunningRestriction.model_validate(raw) if raw is not None else None
