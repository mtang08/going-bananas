from datetime import UTC, date, datetime, timedelta

from app.services.coaching import daily, fingerprint, weekly

TODAY = date(2026, 11, 10)


def context(*, checkin=None, intent='easy', anchor=True, activities=None):
    return {'generated_at': datetime(2026, 11, 10, 12, tzinfo=UTC),
            'profile': {'anchor_confirmed': anchor, 'cycle_anchor': TODAY if anchor else None},
            'recent_checkins': [checkin] if checkin else [], 'recent_activities': activities or [],
            'next_14_days_plan': [{'version': 1, 'decided_at': datetime(2026, 11, 9, tzinfo=UTC),
                                   'sessions': [{'id': 'run1', 'date': TODAY, 'kind': 'run', 'target': {'intent': intent}}]}],
            'recent_14_days_plan': [], 'recovery': {'series': {'hrv': []}},
            'last_14_days': {'rolling_7': {'distance_m': 12000},
                             'rolling_14': {'distance_m': 24000, 'longest_elapsed_s': 3600}}}


def checkin(*, symptoms='none', change='same', gait='normal', feeling='usual', when=None):
    return {'observed_at': when or datetime(2026, 11, 10, 8, tzinfo=UTC),
            'symptoms': symptoms, 'change': change, 'gait': gait, 'feeling': feeling}


def supplement(**changes):
    return {'illness': 'none', 'lower_body_soreness': 'none', 'clinician_restriction': 'none', **changes}


def test_normal_easy_and_unknown_current_symptoms():
    ready = daily(context(checkin=checkin()), TODAY, supplement(), today=TODAY)
    assert ready['decision'] == 'proceed'
    unknown = daily(context(checkin=checkin(when=datetime(2026, 11, 9, 8, tzinfo=UTC))), TODAY,
                    supplement(), today=TODAY)
    assert unknown['decision'] == 'modify'
    assert unknown['proposed_session']['mode'] == 'conditional_easy_run'
    assert unknown['confidence']['decision'] == 'low'


def test_worsening_walking_overrides_favorable_metrics():
    c = context(checkin=checkin(symptoms='mild', change='worse', gait='affected'), intent='long')
    c['recovery']['series']['hrv'] = [{'date': TODAY, 'value': 80}]
    result = daily(c, TODAY, supplement(), today=TODAY)
    assert result['decision'] == 'seek_clinical_input'
    assert result['proposed_session']['mode'] == 'rest'
    assert 'P005' in result['references']['policy_ids']


def test_mild_illness_and_strength_soreness_preserve_frequency():
    mild = daily(context(checkin=checkin(), intent='quality'), TODAY, supplement(illness='mild'), today=TODAY)
    assert mild['decision'] == 'modify' and mild['proposed_session']['mode'] == 'conditional_easy_challenge'
    sore = daily(context(checkin=checkin(), intent='quality'), TODAY,
                 supplement(lower_body_soreness='affects_movement'), today=TODAY)
    assert sore['decision'] == 'modify' and 'P012' in sore['references']['policy_ids']


def test_tomorrow_preview_and_unknown_anchor_are_provisional():
    tomorrow = TODAY + timedelta(days=1)
    c = context(checkin=checkin())
    c['next_14_days_plan'][0]['sessions'][0]['date'] = tomorrow
    result = daily(c, tomorrow, supplement(), today=TODAY)
    assert result['decision'] == 'modify'
    assert 'Future-day' in ' '.join(result['missing_or_stale_inputs'])
    c = context(checkin=checkin(), anchor=False)
    c['next_14_days_plan'] = []
    result = daily(c, TODAY, supplement(), today=TODAY)
    assert result['decision'] == 'modify' and 'anchor' in result['short_rationale']


def test_checkin_before_later_session_is_not_current_response():
    c = context(checkin=checkin(), activities=[{'local_date': TODAY, 'start_at': datetime(2026, 11, 10, 10, tzinfo=UTC),
                                                 'sport': 'running'}])
    result = daily(c, TODAY, supplement(), today=TODAY)
    assert result['decision'] == 'modify'
    assert result['proposed_session']['mode'] == 'conditional_easy_run'


def test_weekly_unknown_unlinked_and_no_tolerance_claim():
    c = context(checkin=None)
    c['recent_14_days_plan'] = [{'sessions': [{'date': TODAY-timedelta(days=1), 'completion_link_id': None}]}]
    result = weekly(c, TODAY)
    assert result['actual_vs_planned']['missed'] is None
    assert 'not classified as missed' in ' '.join(result['uncertainties'])
    assert not result['tolerance_signals']['favorable']
    assert result['observed_training']['rolling_14_km'] == 24
    assert result['next_cycle_proposal']['primary_target'] == 'consolidate continuity'


def test_fingerprint_stable_for_ordered_input():
    assert fingerprint({'b': 2, 'a': 1}) == fingerprint({'a': 1, 'b': 2})


def test_strength_soreness_and_clinical_fallback_preserve_limits():
    c = context(checkin=checkin())
    c['next_14_days_plan'][0]['sessions'][0]['kind'] = 'strength'
    sore = daily(c, TODAY, supplement(lower_body_soreness='affects_movement'), today=TODAY)
    assert sore['proposed_session']['mode'] == 'strength_modified'
    restricted = daily(c, TODAY, supplement(clinician_restriction='restricted'), today=TODAY)
    assert restricted['proposed_session']['mode'] == 'rest'
    assert restricted['alternative']['mode'] == 'rest'
    unknown = daily(c, TODAY, supplement(lower_body_soreness='unknown'), today=TODAY)
    assert unknown['decision'] == 'modify'


def test_weekly_local_time_boundary_and_delayed_association():
    c = context()
    c['timezone'] = 'America/New_York'
    c['recent_checkins'] = [
        checkin(symptoms='mild', change='worse', when=datetime(2026, 11, 11, 2, tzinfo=UTC))
        | {'associations': [{'kind': 'running', 'elapsed_hours': 24}]},
        checkin(symptoms='none', change='same', when=datetime(2026, 10, 27, 2, tzinfo=UTC)),
    ]
    result = weekly(c, TODAY)
    assert '1 worsening check-in' in result['tolerance_signals']['delayed_symptom_findings'][0]
    assert result['next_cycle_proposal']['primary_target'] == 'reduce mechanical load while preserving aerobic work'
    assert 'Wednesday' not in str(result)


def test_safety_precedence_for_mixed_quality_day_inputs():
    c = context(checkin=checkin(feeling='tired'), intent='quality')
    mild = daily(c, TODAY, supplement(illness='mild'), today=TODAY)
    assert mild['proposed_session']['mode'] == 'conditional_easy_challenge'
    c['recent_checkins'] = [checkin(symptoms='mild', change='worse', feeling='tired')]
    worse = daily(c, TODAY, supplement(), today=TODAY)
    assert worse['proposed_session']['mode'] == 'rest_or_tolerated_low_impact'
    c['recent_checkins'] = [checkin(feeling='tired')]
    sore = daily(c, TODAY, supplement(lower_body_soreness='affects_movement'), today=TODAY)
    assert sore['proposed_session']['mode'] == 'easy_or_rest'
    c['recent_checkins'] = [checkin(gait='unsure')]
    unsure = daily(c, TODAY, supplement(), today=TODAY)
    assert unsure['decision'] == 'modify'
    assert 'uncertain' in ' '.join(unsure['missing_or_stale_inputs'])
