"""Current athlete profile query and wire data helpers."""
from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import ProfileVersion
from app.services.timezone import DEFAULT_TIMEZONE


def current_profile(session: Session) -> ProfileVersion | None:
    return session.scalar(select(ProfileVersion).order_by(desc(ProfileVersion.version)).limit(1))


def profile_data(profile: ProfileVersion | None, planning_authority: str = 'legacy') -> dict:
    if profile is None:
        return {'version': 0, 'planning_authority': planning_authority, 'timezone': DEFAULT_TIMEZONE, 'cycle_anchor': None,
                'anchor_confirmed': False, 'strength_days_confirmed': False,
                'scheduled_strength_days': [], 'strength_schedule_mode': 'weekly',
                'strength_week_a_start': None, 'strength_week_a_days': [], 'strength_week_b_days': [],
                'mobility_week_a_days': [], 'mobility_week_b_days': [], 'mobility_optional_days': [],
                'facts': {}, 'preferences': {}, 'unknowns': []}
    return {'planning_authority': planning_authority, **{key: getattr(profile, key) for key in ('version', 'timezone', 'cycle_anchor', 'anchor_confirmed',
            'strength_days_confirmed', 'scheduled_strength_days', 'strength_schedule_mode',
            'strength_week_a_start', 'strength_week_a_days', 'strength_week_b_days',
            'mobility_week_a_days', 'mobility_week_b_days', 'mobility_optional_days',
            'facts', 'preferences', 'unknowns')}}
