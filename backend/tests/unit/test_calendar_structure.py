from __future__ import annotations

import math

import pytest

from app.services.calendar_structure import StructureError, expand_structure, work_signature


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


def test_work_signature_groups_equivalent_workouts():
    def s(kind, dtype, value, modality='effort'):
        target = ({'modality': 'effort', 'low': None, 'high': None, 'effort_cue': 'x'}
                  if modality == 'effort' else
                  {'modality': 'speed', 'low': 3.4, 'high': 3.8, 'effort_cue': None})
        return {'type': kind, 'duration_type': dtype, 'duration_value': value, 'target': target}
    def repeat(count, dtype, value, recovery=120, modality='effort'):
        return {'type': 'repeat', 'count': count, 'steps': [s('work', dtype, value, modality),
                                                            s('recovery', 'time', recovery)]}
    wu, cd = s('warmup', 'time', 600), s('cooldown', 'time', 600)
    assert work_signature([wu, repeat(4, 'time', 300, modality='speed'), cd]) == 'ws1:4xt300'
    assert work_signature([wu, repeat(4, 'time', 300, 90), cd]) == 'ws1:4xt300'
    assert work_signature([wu, repeat(4, 'time', 180), s('work', 'time', 180), cd]) == 'ws1:5xt180'
    assert work_signature([wu, repeat(5, 'time', 180), cd]) == 'ws1:5xt180'
    assert work_signature([repeat(6, 'distance', 804.672, 90)]) == 'ws1:6xd800'
    assert work_signature([repeat(6, 'distance', 800, 90)]) == 'ws1:6xd800'
    assert work_signature([repeat(3, 'distance', 1609.344)]) == 'ws1:3xd1610'
    assert work_signature([repeat(3, 'distance', 1000)]) == 'ws1:3xd1000'
    assert work_signature([s('work', 'time', n) for n in (60, 120, 180, 120, 60)]) == 'ws1:1xt60+1xt120+1xt180+1xt120+1xt60'
    assert work_signature([repeat(3, 'distance', 1000), repeat(4, 'distance', 200, 60)]) == 'ws1:3xd1000+4xd200'
    assert work_signature([wu, s('work', 'time', 1200), cd]) == 'ws1:1xt1200'
    assert work_signature([s('work', 'time', n) for n in (302.5, 307.5, 297)]) == 'ws1:1xt300+1xt310+1xt295'
    assert all(work_signature(value) is None for value in (None, [], [wu, cd]))
    with pytest.raises(StructureError):
        work_signature([{'type': 'work'}])
