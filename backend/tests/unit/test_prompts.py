from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from app.services import prompts
from app.services.prompts import prompt_changes

END = datetime(2026, 11, 15, 14, tzinfo=UTC)
START = END - timedelta(hours=1)
ACTIVITY = '00000000-0000-0000-0000-000000000001'
SESSION = '00000000-0000-0000-0000-000000000002'


def facts(**changes) -> dict:
    base = {
        'activities': [{'id': ACTIVITY, 'start_at': START, 'end_at': END,
                        'effective_rpe': None, 'is_long': True}],
        'checkins': [], 'completions': [], 'planned_actual': [],
        'local_today': date(2026, 11, 16), 'timezone': 'America/New_York',
        'valid_subjects': {'activity': [ACTIVITY], 'strong_workout': [], 'manual_session': []},
    }
    return {**base, **changes}


def row(item: dict, *, status: str | None = None, id: str = 'prompt-1') -> dict:
    return {**item, 'id': id, 'status': status or item['status']}


def visible(prompt: dict, now: datetime) -> bool:
    return (prompt['status'] == 'open' and prompt['opens_at'] <= now
            and (prompt['closes_at'] is None or prompt['closes_at'] > now))


def test_future_delayed_created_and_visibility_boundary() -> None:
    changes = prompt_changes(facts(), [], END)
    delayed = next(item for item in changes['create'] if item['kind'] == 'delayed_symptom')
    assert delayed['activity_id'] == ACTIVITY
    assert delayed['opens_at'] == datetime(2026, 11, 16, 6, tzinfo=UTC)
    assert delayed['closes_at'] == datetime(2026, 11, 17, 14, tzinfo=UTC)
    assert changes['counts'] == {'created': 2, 'expired': 0, 'answered': 0}
    assert not visible(delayed, delayed['opens_at'] - timedelta(seconds=1))
    assert visible(delayed, delayed['opens_at'])
    assert not visible(delayed, delayed['closes_at'])
    assert prompt_changes(facts(), [row(item, id=str(i)) for i, item in enumerate(changes['create'])], END)['counts'] == {
        'created': 0, 'expired': 0, 'answered': 0}


def test_unknown_end_or_not_finished_has_no_timed_prompt() -> None:
    activity = facts()['activities'][0]
    assert prompt_changes(facts(activities=[{**activity, 'end_at': None}]), [], END)['create'] == []
    assert prompt_changes(facts(), [], END - timedelta(seconds=1))['create'] == []


def test_zero_rpe_is_answered_and_dismissal_is_sticky() -> None:
    activity = {**facts()['activities'][0], 'effective_rpe': 0, 'is_long': False}
    changes = prompt_changes(facts(activities=[activity]), [], END)
    assert changes['create'][0]['kind'] == 'rpe'
    assert changes['create'][0]['status'] == 'answered'
    assert changes['counts'] == {'created': 1, 'expired': 0, 'answered': 1}
    prior = row(changes['create'][0], status='dismissed')
    assert prompt_changes(facts(activities=[activity]), [prior], END)['counts'] == {
        'created': 0, 'expired': 0, 'answered': 0}
    assert prompt_changes(facts(activities=[activity]), [prior], END)['update'] == []


def test_empty_explicit_delayed_followup_answers_but_unrelated_checkin_does_not() -> None:
    base = prompt_changes(facts(), [], END)
    old = [row(item, id='delayed-id' if item['kind'] == 'delayed_symptom' else 'rpe-id')
           for item in base['create']]
    unrelated = [
        {'kind': 'exception', 'activity_id': ACTIVITY, 'prompt_id': 'delayed-id',
         'observed_at': END + timedelta(hours=24), 'symptoms': [3]},
        {'kind': 'delayed_followup', 'activity_id': 'other', 'prompt_id': None,
         'observed_at': END + timedelta(hours=24), 'symptoms': [4]},
    ]
    unchanged = prompt_changes(facts(checkins=unrelated), old, END + timedelta(hours=24))
    assert unchanged['counts']['answered'] == 0
    explicit = unrelated + [{'kind': 'delayed_followup', 'activity_id': None,
                             'prompt_id': 'delayed-id', 'observed_at': END + timedelta(hours=24),
                             'symptoms': []}]
    answered = prompt_changes(facts(checkins=explicit), old, END + timedelta(hours=24))
    assert answered['counts']['answered'] == 1
    assert answered['update'] == [{'key': f'delayed_symptom:{ACTIVITY}', 'status': 'answered'}]


def test_derived_unknown_does_not_answer_missing_or_unmatched_prompt() -> None:
    result = {'session_uid': SESSION, 'kind': 'run', 'local_date': date(2026, 11, 15),
              'reason_codes': ['NO_ACTIVITY_FOUND', 'AMBIGUOUS_MATCH'], 'certainty': 'provisional'}
    completion = {'session_uid': SESSION, 'status': 'unknown', 'match_method': 'none',
                  'activity_id': None, 'strong_workout_id': None, 'manual_session_id': None}
    changes = prompt_changes(facts(activities=[], planned_actual=[result],
                                   completions=[completion]), [], END)
    assert {item['kind'] for item in changes['create']} == {'missing_activity', 'unmatched_session'}
    assert all(item['status'] == 'open' for item in changes['create'])
    assert changes['counts'] == {'created': 2, 'expired': 0, 'answered': 0}
    explicit = {**completion, 'match_method': 'user_marked'}
    marked = prompt_changes(facts(activities=[], planned_actual=[result],
                                  completions=[explicit]), [], END)
    assert all(item['status'] == 'answered' for item in marked['create'])
    assert marked['counts']['answered'] == 2


def test_valid_link_answers_regardless_of_computed_status() -> None:
    result = {'session_uid': SESSION, 'kind': 'run', 'local_date': date(2026, 11, 15),
              'reason_codes': ['MOVE_CANDIDATE'], 'status': 'not_assessable'}
    completion = {'session_uid': SESSION, 'status': 'unknown', 'match_method': 'explicit',
                  'activity_id': ACTIVITY, 'strong_workout_id': None, 'manual_session_id': None}
    changes = prompt_changes(facts(activities=[], planned_actual=[result],
                                   completions=[completion]), [], END)
    assert changes['create'][0]['status'] == 'answered'


def test_existing_match_answers_after_reason_disappears_or_window_passes() -> None:
    old = {'id': 'prompt-1', 'kind': 'missing_activity', 'activity_id': None,
           'session_uid': SESSION, 'opens_at': END, 'closes_at': None, 'status': 'open'}
    linked = {'session_uid': SESSION, 'status': 'completed_modified', 'match_method': 'explicit',
              'activity_id': ACTIVITY, 'strong_workout_id': None, 'manual_session_id': None}
    changes = prompt_changes(facts(activities=[], planned_actual=[], completions=[linked]), [old], END)
    assert changes['update'] == [{'key': f'missing_activity:{SESSION}', 'status': 'answered'}]
    assert changes['counts'] == {'created': 0, 'expired': 0, 'answered': 1}
    explicit = {'session_uid': SESSION, 'status': 'unknown', 'match_method': 'user_marked',
                'activity_id': None, 'strong_workout_id': None, 'manual_session_id': None}
    late = prompt_changes(facts(activities=[], planned_actual=[], completions=[explicit],
                                local_today=date(2026, 12, 10)),
                          [{**old, 'status': 'expired'}], END + timedelta(days=24))
    assert late['update'] == [{'key': f'missing_activity:{SESSION}', 'status': 'answered'}]
    assert late['counts']['answered'] == 1


def test_invalid_link_does_not_answer_or_reopen() -> None:
    result = {'session_uid': SESSION, 'kind': 'run', 'local_date': date(2026, 11, 15),
              'reason_codes': ['NO_ACTIVITY_FOUND']}
    bad = {'session_uid': SESSION, 'status': 'unknown', 'match_method': 'user_marked',
           'activity_id': 'excluded-run', 'strong_workout_id': None, 'manual_session_id': None}
    changes = prompt_changes(facts(activities=[], planned_actual=[result], completions=[bad]), [], END)
    assert changes['create'][0]['status'] == 'open'
    assert changes['counts']['answered'] == 0


def test_canonical_loader_excludes_conflicted_or_excluded_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    eligible = SimpleNamespace(id=UUID(ACTIVITY), start_at=END)
    excluded = SimpleNamespace(id=UUID(SESSION), start_at=END)
    def fake_load_runs(_session, start, end):
        assert start == date(2026, 11, 15)
        assert end == date(2026, 11, 16)
        return [SimpleNamespace(activity_id=eligible.id)]
    monkeypatch.setattr(prompts, 'load_runs', fake_load_runs)
    assert prompts._eligible_run_rows(object(), [eligible, excluded], ZoneInfo('UTC')) == [eligible]


def test_old_match_prompts_expire_when_plan_matches_or_disappears() -> None:
    result = {'session_uid': SESSION, 'kind': 'run', 'local_date': date(2026, 11, 15),
              'reason_codes': ['NO_ACTIVITY_FOUND']}
    created = prompt_changes(facts(activities=[], planned_actual=[result]), [], END)['create']
    old = [row(created[0])]
    changes = prompt_changes(facts(activities=[], planned_actual=[]), old, END + timedelta(hours=1))
    assert changes['update'] == [{'key': f'missing_activity:{SESSION}', 'status': 'expired'}]
    assert changes['counts']['expired'] == 1
    assert prompt_changes(facts(activities=[], planned_actual=[]),
                          [row(created[0], status='dismissed')], END)['update'] == []


def test_late_expired_delayed_answer_never_reopens() -> None:
    original = prompt_changes(facts(), [], END)['create']
    delayed = next(item for item in original if item['kind'] == 'delayed_symptom')
    expired = row(delayed, status='expired', id='delayed-id')
    late = END + timedelta(hours=49)
    checkin = {'kind': 'delayed_followup', 'activity_id': ACTIVITY, 'prompt_id': None,
               'observed_at': late, 'symptoms': []}
    changes = prompt_changes(facts(checkins=[checkin]), [expired], late)
    assert changes['update'] == [{'key': f'delayed_symptom:{ACTIVITY}', 'status': 'answered'}]
    assert changes['counts']['answered'] == 1
    assert changes['counts']['expired'] == 1  # Late, unanswered RPE is stored expired.
    assert prompt_changes(facts(), [row(delayed, status='expired')], late)['update'] == []


def test_missing_prior_seven_days_and_unmatched_today() -> None:
    results = [
        {'session_uid': 'old', 'kind': 'run', 'local_date': date(2026, 11, 9),
         'reason_codes': ['NO_ACTIVITY_FOUND'], 'certainty': 'provisional'},
        {'session_uid': 'today', 'kind': 'run', 'local_date': date(2026, 11, 16),
         'reason_codes': ['NO_ACTIVITY_FOUND', 'MOVE_CANDIDATE'], 'certainty': 'provisional'},
        {'session_uid': 'older', 'kind': 'run', 'local_date': date(2026, 11, 8),
         'reason_codes': ['NO_ACTIVITY_FOUND', 'AMBIGUOUS_MATCH']},
    ]
    changes = prompt_changes(facts(activities=[], planned_actual=results), [], END)
    assert {item['key'] for item in changes['create']} == {
        'missing_activity:old', 'unmatched_session:today',
    }


def test_symptom_history_qualifies_nonlong_run_and_dst_uses_utc_elapsed() -> None:
    local_end = datetime(2026, 3, 8, 10, tzinfo=ZoneInfo('America/New_York'))
    activity = {'id': ACTIVITY, 'start_at': local_end - timedelta(hours=1),
                'end_at': local_end, 'effective_rpe': None, 'is_long': False}
    symptom = {'kind': 'exception', 'activity_id': None, 'prompt_id': None,
               'observed_at': activity['start_at'] - timedelta(days=1), 'symptoms': [2]}
    end_utc = local_end.astimezone(UTC)
    changes = prompt_changes(facts(activities=[activity], checkins=[symptom]), [], end_utc)
    delayed = next(item for item in changes['create'] if item['kind'] == 'delayed_symptom')
    assert delayed['opens_at'] == end_utc + timedelta(hours=16)
    assert delayed['closes_at'] == end_utc + timedelta(hours=48)
