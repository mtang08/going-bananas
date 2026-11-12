"""Validate and expand the one-level calendar step language."""
from __future__ import annotations

import math
from copy import deepcopy
from typing import cast

STEP_TYPES = {'warmup', 'work', 'recovery', 'cooldown'}
DURATION_TYPES = {'time', 'distance'}
MODALITIES = {'speed', 'hr', 'effort'}


class StructureError(ValueError):
    pass


def _number(value: object, *, positive: bool = False) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def _step(value: object) -> dict:
    if not isinstance(value, dict) or set(value) - {'type', 'duration_type', 'duration_value', 'target'}:
        raise StructureError('invalid_structure')
    if value.get('type') not in STEP_TYPES or value.get('duration_type') not in DURATION_TYPES:
        raise StructureError('invalid_structure')
    if not _number(value.get('duration_value'), positive=True):
        raise StructureError('invalid_structure')
    target = value.get('target')
    if target is not None:
        if not isinstance(target, dict) or set(target) - {'modality', 'low', 'high', 'effort_cue'}:
            raise StructureError('invalid_structure')
        modality = target.get('modality')
        low, high = target.get('low'), target.get('high')
        cue = target.get('effort_cue')
        if modality not in MODALITIES:
            raise StructureError('invalid_structure')
        if modality == 'effort':
            if low is not None or high is not None or not isinstance(cue, str) or not cue.strip():
                raise StructureError('invalid_structure')
        else:
            if not _number(low, positive=(modality == 'hr')) or not _number(high, positive=(modality == 'hr')):
                raise StructureError('invalid_structure')
            if cast(float, low) > cast(float, high) or (cue is not None and (not isinstance(cue, str) or not cue.strip())):
                raise StructureError('invalid_structure')
    return deepcopy(value)


def expand_structure(structure: list[dict]) -> list[dict]:
    if not isinstance(structure, list) or not structure:
        raise StructureError('invalid_structure')
    expanded: list[dict] = []
    def append(step: dict, path: str, repeat_index: int | None) -> None:
        if len(expanded) >= 100:
            raise StructureError('invalid_structure')
        expanded.append({**step, 'step_path': path,
                         'expanded_step': len(expanded) + 1, 'repeat_index': repeat_index})
    for index, item in enumerate(structure):
        if isinstance(item, dict) and item.get('type') == 'repeat':
            if set(item) != {'type', 'count', 'steps'} or type(item['count']) is not int or item['count'] < 2:
                raise StructureError('invalid_structure')
            children = item['steps']
            if not isinstance(children, list) or not children:
                raise StructureError('invalid_structure')
            validated = [_step(child) for child in children]
            if len(expanded) + item['count'] * len(validated) > 100:
                raise StructureError('invalid_structure')
            for repetition in range(item['count']):
                for child_index, child in enumerate(validated):
                    append(child, f'{index}.steps.{child_index}', repetition)
        else:
            append(_step(item), str(index), None)
    return expanded
