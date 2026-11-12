from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from app.services.daily_guidance import DailyInputs, daily_v2

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)


def base(**changes):
    value = DailyInputs(today=date(2026, 11, 16), as_of=date(2026, 11, 16),
        session_uid=uuid.uuid4(), session_kind='run', intent='Quality intervals',
        has_plan=True, anchor_confirmed=True, fatigue=None, illness=None,
        gait_change=None, symptoms=(), prior_symptoms=(), clinical_restriction=None,
        legacy_safety_active=False, missed_committed_runs=0,
        delayed_symptom_reported=False)
    return replace(value, **changes)


def symptom(severity, *, observed=NOW, side='left', site='Achilles'):
    return {'site': site, 'side': side, 'severity': severity, 'observed_at': observed,
            'recorded_at': observed, 'id': str(uuid.uuid4())}


def test_unknown_inputs_do_not_downgrade_planned_quality():
    result = daily_v2(base())
    assert result['decision'] == 'proceed'
    assert result['missing_inputs'] == ['fatigue', 'illness', 'gait_change', 'clinical_restriction']
    assert result['trigger_codes'] == []
    assert result['coach_review_suggested'] is False
    assert daily_v2(base(fatigue=7))['decision'] == 'modify'
    assert daily_v2(base(legacy_safety_active=True))['decision'] == 'seek_clinical_input'


@pytest.mark.parametrize(('severity', 'decision'), [(0, 'proceed'), (3.0, 'modify'),
    (3.1, 'modify'), (6.4, 'modify'), (6.5, 'modify')])
def test_continuous_symptom_bands(severity, decision):
    result = daily_v2(base(symptoms=(symptom(severity),)))
    assert result['decision'] == decision
    assert ('moderate_symptoms' in result['trigger_codes']) is (severity > 3)


def test_branch_priority_and_worsening_within_same_site_side():
    current = symptom(4)
    prior = symptom(3, observed=NOW - timedelta(days=3))
    result = daily_v2(base(symptoms=(current,), prior_symptoms=(prior,)))
    assert result['decision'] == 'seek_clinical_input'
    assert 'worsening_symptoms' in result['trigger_codes']
    other_side = symptom(3, observed=NOW - timedelta(days=3), side='right')
    assert daily_v2(base(symptoms=(current,), prior_symptoms=(other_side,)))['decision'] == 'modify'
    too_old = symptom(3, observed=NOW - timedelta(days=8))
    assert daily_v2(base(symptoms=(current,), prior_symptoms=(too_old,)))['decision'] == 'modify'
    same_observed = symptom(3, observed=NOW)
    assert daily_v2(base(symptoms=(current,), prior_symptoms=(same_observed,)))['decision'] == 'modify'
    assert daily_v2(base(symptoms=(current,), prior_symptoms=(prior,), gait_change='yes'))['decision'] == 'seek_clinical_input'
    restriction = daily_v2(base(symptoms=(current,), prior_symptoms=(prior,),
        clinical_restriction='restricted', illness='present'))
    assert restriction['policy_ids'] == ['P018']


def test_no_plan_future_and_review_flags():
    assert daily_v2(base(has_plan=False, anchor_confirmed=False))['decision'] == 'modify'
    assert daily_v2(base(as_of=date(2026, 11, 17)))['decision'] == 'modify'
    result = daily_v2(base(missed_committed_runs=2, delayed_symptom_reported=True))
    assert result['decision'] == 'proceed'
    assert result['coach_review_suggested'] is True
    assert result['trigger_codes'] == ['repeated_missed_runs', 'delayed_symptoms_reported']
