"""Coach operations: the one source for every registration site."""

from __future__ import annotations

from typing import Literal, get_args

Operation = Literal[
    "proceed_or_modify_today",
    "review_rolling_plan",
    "select_quality_session",
    "review_training_block",
    "recalibrate_intensity",
    "handle_goal_or_race_change",
    "exception_review",
    "post_event_review",
]
OPERATIONS: tuple[Operation, ...] = get_args(Operation)
