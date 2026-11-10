from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def preceding_sessions(observed_at: datetime, sessions: list[dict], timezone_name: str, hours: int = 72) -> list[dict]:
    if observed_at.tzinfo is None:
        raise ValueError('observed_at needs offset')
    zone = ZoneInfo(timezone_name)
    local_day = observed_at.astimezone(zone).date()
    result = []
    for session in sessions:
        start = session['start_at']
        if start.tzinfo is None:
            continue
        elapsed = session.get('elapsed_s')
        end = start.astimezone(UTC) + timedelta(seconds=elapsed) if elapsed is not None else start.astimezone(UTC)
        delta = (observed_at.astimezone(UTC)-end).total_seconds()/3600
        if 0 <= delta <= hours:
            day_diff = (local_day - start.astimezone(zone).date()).days
            result.append({'activity_id': str(session['id']), 'kind': session['sport'],
                           'elapsed_hours': delta if elapsed is not None else None,
                           'timing_uncertain': elapsed is None,
                           'day_label': 'same_day' if day_diff == 0 else 'next_day' if day_diff == 1 else 'second_day' if day_diff == 2 else 'later'})
    return sorted(result, key=lambda item: (item['elapsed_hours'] is None, item['elapsed_hours'] or 0))
