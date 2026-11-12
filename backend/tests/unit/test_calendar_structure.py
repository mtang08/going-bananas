from __future__ import annotations

import math

import pytest

from app.services.calendar_structure import StructureError, expand_structure


def step(kind='work', duration=60, target=None):
    return {'type': kind, 'duration_type': 'time', 'duration_value': duration, 'target': target}


def test_repeat_expands_in_execution_order_with_paths():
    structure = [step('warmup'), {'type': 'repeat', 'count': 2,
        'steps': [step('work'), step('recovery')]}]
    result = expand_structure(structure)
    assert [item['type'] for item in result] == ['warmup', 'work', 'recovery', 'work', 'recovery']
    assert [item['expanded_step'] for item in result] == [1, 2, 3, 4, 5]
    assert [item['step_path'] for item in result] == ['0', '1.steps.0', '1.steps.1', '1.steps.0', '1.steps.1']
    assert [item['repeat_index'] for item in result] == [None, 0, 0, 1, 1]
    assert all(item['target'] is None for item in result)


@pytest.mark.parametrize('structure', [[], [{'type': 'repeat', 'count': 1, 'steps': [step()]}],
    [{'type': 'repeat', 'count': 2, 'steps': []}],
    [{'type': 'repeat', 'count': 2, 'steps': [{'type': 'repeat', 'count': 2, 'steps': [step()]}]}],
    [step(duration=math.nan)], [step(target={'modality': 'speed', 'low': 3, 'high': 2})],
    [step(target={'modality': 'effort', 'low': None, 'high': None, 'effort_cue': ' '})],
    [step() | {'unexpected': 1}], [{'type': 'repeat', 'count': 101, 'steps': [step()]}]])
def test_invalid_structures(structure):
    with pytest.raises(StructureError):
        expand_structure(structure)
