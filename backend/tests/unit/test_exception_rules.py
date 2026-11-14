from typing import get_args

from app.services.exceptions.vocab import (
    CATEGORY,
    FINDING_STATUS,
    LADDER,
    NON_TERMINAL_FINDING,
    PATCH_CATEGORY,
    PATCH_STATUS,
    RULE_VERSION,
    SEVERITY,
    TERMINAL_FINDING,
    Severity,
    max_severity,
)


def test_vocab() -> None:
    assert max_severity('observe', 'hold') == 'hold'
    assert max_severity('escalate', 'caution', 'observe') == 'escalate'
    assert SEVERITY == ('observe', 'caution', 'hold', 'escalate')
    assert CATEGORY == ('symptoms_illness', 'training_response', 'accumulated_fatigue', 'calendar_disruption', 'post_event')
    assert PATCH_CATEGORY == tuple(category for category in CATEGORY if category != 'post_event')
    assert FINDING_STATUS == NON_TERMINAL_FINDING + TERMINAL_FINDING
    assert PATCH_STATUS == ('open', 'resolved', 'escalated', 'superseded')
    assert LADDER == ('current_session', 'next_session', 'next_days', 'committed_window', 'block')
    assert get_args(Severity) == SEVERITY
    assert RULE_VERSION == 'exceptions.v1'
