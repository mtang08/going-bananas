"""Athlete-confirmed temporary running availability."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

RUNNING_INTERRUPTION_KEY = "running_interruption"
InterruptionPhase = Literal["planned", "paused", "review_due", "returning"]


class RunningInterruption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["schedule", "travel", "illness", "other"]
    starts_on: date
    return_on: date | None = None
    review_on: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> RunningInterruption:
        if (self.return_on is None) == (self.review_on is None):
            raise ValueError("Give either a confirmed return date or a review date")
        if self.return_on is not None and self.return_on <= self.starts_on:
            raise ValueError("The first available day must be after the first unavailable day")
        if self.review_on is not None and self.review_on < self.starts_on:
            raise ValueError("The review cannot be before the first unavailable day")
        return self

    def unavailable_on(self, day: date) -> bool:
        return self.starts_on <= day and (self.return_on is None or day < self.return_on)

    def phase_on(self, today: date) -> InterruptionPhase:
        if today < self.starts_on:
            return "planned"
        if self.return_on is not None and today >= self.return_on:
            return "returning"
        if self.review_on is not None and today >= self.review_on:
            return "review_due"
        return "paused"


def running_interruption(facts: dict[str, Any] | None) -> RunningInterruption | None:
    raw = (facts or {}).get(RUNNING_INTERRUPTION_KEY)
    return RunningInterruption.model_validate(raw) if raw is not None else None
