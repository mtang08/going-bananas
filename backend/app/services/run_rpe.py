"""Effective run RPE: manual, then Garmin FIT, then the activity's workout RPE."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any


def effective_run_rpe(rows: Iterable[Any], workout_rpe: float | None) -> tuple[float | None, str | None, datetime | None]:
    ordered = sorted(rows, key=lambda r: (r.collected_at, str(r.id)))
    chosen = (next((r for r in reversed(ordered) if r.source == 'manual'), None)
              or next((r for r in reversed(ordered) if r.source == 'garmin_fit'), None))
    if chosen is not None:
        return chosen.rpe, chosen.source, chosen.collected_at
    if workout_rpe is not None:
        return workout_rpe, 'garmin_fit', None
    return None, None, None
