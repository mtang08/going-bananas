"""Session classes and expected whole-session RPE (session_class.v1)."""
from __future__ import annotations

from typing import Literal

SESSION_CLASS_VERSION = 'session_class.v1'
SessionClass = Literal['easy', 'long', 'quality', 'benchmark', 'cross', 'strength', 'mobility', 'rest', 'unknown']
Mismatch = Literal['above', 'below']
QUALITY_CLASSES: frozenset[str] = frozenset({'quality', 'benchmark'})
HARD_CLASSES: frozenset[str] = frozenset({'quality', 'long', 'benchmark'})
MISMATCH_MARGIN = 2.0
RECIPE_CLASS: dict[str, SessionClass] = {
    'REC001': 'easy', 'REC002': 'long', 'REC003': 'quality', 'REC004': 'quality', 'REC005': 'quality',
    'REC006': 'quality', 'REC007': 'easy', 'REC008': 'quality', 'REC009': 'benchmark', 'REC010': 'cross',
}
RECIPE_EXPECTED_RPE: dict[str, tuple[float, float]] = {
    'REC001': (2.0, 4.0), 'REC002': (3.0, 5.0), 'REC003': (5.0, 7.0), 'REC004': (5.0, 7.0),
    'REC005': (6.0, 8.0), 'REC006': (5.0, 7.0), 'REC007': (2.0, 4.0), 'REC008': (5.0, 7.0),
}
CLASS_EXPECTED_RPE: dict[str, tuple[float, float]] = {'easy': (2.0, 4.0), 'long': (3.0, 5.0), 'quality': (5.0, 8.0)}
QUALITY_RECIPES: frozenset[str] = frozenset(r for r, c in RECIPE_CLASS.items() if c in QUALITY_CLASSES)
LONG_RECIPE = 'REC002'
_KIND_CLASS: dict[str, SessionClass] = {'cross': 'cross', 'strength': 'strength', 'mobility': 'mobility', 'rest': 'rest'}
_INTENT_RULES: tuple[tuple[tuple[str, ...], SessionClass], ...] = (
    (('race', 'benchmark', 'time trial'), 'benchmark'),
    (('long',), 'long'),
    (('interval', 'tempo', 'threshold', 'quality', 'hill', 'vo2', 'fartlek'), 'quality'),
    (('easy', 'recovery', 'shakeout'), 'easy'),
)
_EVALUATED = frozenset({'easy', 'long', 'quality'})


def classify(kind: str, recipe_id: str | None, intent: str | None) -> SessionClass:
    if kind in _KIND_CLASS:
        return _KIND_CLASS[kind]
    if kind != 'run':
        return 'unknown'
    if recipe_id is not None:
        return RECIPE_CLASS.get(recipe_id, 'unknown')
    text = (intent or '').casefold()
    for words, cls in _INTENT_RULES:
        if any(word in text for word in words):
            return cls
    return 'unknown'


def expected_rpe(recipe_id: str | None, cls: str) -> tuple[float, float] | None:
    if recipe_id is not None:
        return RECIPE_EXPECTED_RPE.get(recipe_id)
    return CLASS_EXPECTED_RPE.get(cls)


def rpe_mismatch(cls: str, recipe_id: str | None, rpe: float | None) -> Mismatch | None:
    if rpe is None or cls not in _EVALUATED:
        return None
    bounds = expected_rpe(recipe_id, cls)
    if bounds is None:
        return None
    if rpe >= bounds[1] + MISMATCH_MARGIN:
        return 'above'
    if cls == 'quality' and rpe <= bounds[0] - MISMATCH_MARGIN:
        return 'below'
    return None
