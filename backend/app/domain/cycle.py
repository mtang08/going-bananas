from __future__ import annotations

from collections import Counter
from datetime import date, timedelta


def opportunity(day: date, anchor: date | None) -> dict | None:
    if anchor is None or (day-anchor).days % 2:
        return None
    offset = (day-anchor).days
    return {'date': day.isoformat(), 'fortnight_index': offset // 14, 'slot': (offset % 14)//2}


def opportunities(start: date, end: date, anchor: date | None) -> list[dict]:
    return [item for i in range((end-start).days+1) if (item := opportunity(start+timedelta(days=i), anchor)) is not None]


def validate_acceptance(start: date, end: date, sessions: list[dict], anchor: date | None,
                        anchor_confirmed: bool, strength_days_confirmed: bool) -> list[str]:
    errors: list[str] = []
    if not anchor or not anchor_confirmed:
        errors.append('Confirmed run cycle anchor required')
    if not strength_days_confirmed:
        errors.append('Strength schedule confirmation required')
    runs = [date.fromisoformat(s['date']) for s in sessions if s['kind'] == 'run']
    if len(runs) != len(set(runs)):
        errors.append('Duplicate run date')
    if anchor and any(opportunity(d, anchor) is None for d in runs):
        errors.append('Run date outside cycle parity')
    if any(d < start or d > end for d in runs):
        errors.append('Session outside plan range')
    # Every eligible opportunity in the accepted range must have a proposed run.
    if anchor and set(runs) != {date.fromisoformat(x['date']) for x in opportunities(start, end, anchor)}:
        errors.append('Run opportunities incomplete or extra')
    strengths = Counter(date.fromisoformat(s['date']) - timedelta(days=date.fromisoformat(s['date']).weekday())
                        for s in sessions if s['kind'] == 'strength')
    cursor = start - timedelta(days=start.weekday())
    while cursor + timedelta(days=6) <= end:
        if cursor >= start and strengths[cursor] != 2:
            errors.append(f'Expected two strength sessions in week {cursor.isoformat()}')
        cursor += timedelta(days=7)
    return errors
