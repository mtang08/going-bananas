"""Current athlete profile query and wire data helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db import bump_data_revision, global_write_lock
from app.errors import fail
from app.models import ProfileVersion
from app.services.timezone import DEFAULT_TIMEZONE


def current_profile(session: Session) -> ProfileVersion | None:
    return session.scalar(select(ProfileVersion).order_by(desc(ProfileVersion.version)).limit(1))


def profile_data(profile: ProfileVersion | None) -> dict:
    if profile is None:
        return {
            "version": 0,
            "timezone": DEFAULT_TIMEZONE,
            "cycle_anchor": None,
            "anchor_confirmed": False,
            "strength_days_confirmed": False,
            "scheduled_strength_days": [],
            "strength_schedule_mode": "weekly",
            "strength_week_a_start": None,
            "strength_week_a_days": [],
            "strength_week_b_days": [],
            "mobility_week_a_days": [],
            "mobility_week_b_days": [],
            "mobility_optional_days": [],
            "facts": {},
            "preferences": {},
            "unknowns": [],
        }
    return {
        **{
            key: getattr(profile, key)
            for key in (
                "version",
                "timezone",
                "cycle_anchor",
                "anchor_confirmed",
                "strength_days_confirmed",
                "scheduled_strength_days",
                "strength_schedule_mode",
                "strength_week_a_start",
                "strength_week_a_days",
                "strength_week_b_days",
                "mobility_week_a_days",
                "mobility_week_b_days",
                "mobility_optional_days",
                "facts",
                "preferences",
                "unknowns",
            )
        }
    }


def profile_for_write(session: Session, expected_version: int) -> ProfileVersion | None:
    global_write_lock(session)
    current = current_profile(session)
    if expected_version != (current.version if current else 0):
        fail("version_conflict", "Profile changed; reload /api/v1/profile", 409)
    return current


def append_profile_version(session: Session, current: ProfileVersion | None, fields: dict[str, Any]) -> ProfileVersion:
    profile = ProfileVersion(
        version=(current.version if current else 0) + 1,
        effective_at=datetime.now(UTC),
        **fields,
    )
    session.add(profile)
    bump_data_revision(session)
    return profile
