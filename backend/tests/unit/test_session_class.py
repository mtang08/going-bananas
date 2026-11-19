import pytest

from app.domain.session_class import (
    HARD_CLASSES,
    LONG_RECIPE,
    MISMATCH_MARGIN,
    QUALITY_CLASSES,
    QUALITY_RECIPES,
    RECIPE_CLASS,
    SESSION_CLASS_VERSION,
    classify,
    expected_rpe,
    rpe_mismatch,
)


@pytest.mark.parametrize(
    ('recipe_id', 'cls', 'rpe'),
    [
        ('REC001', 'easy', (2.0, 4.0)),
        ('REC002', 'long', (3.0, 5.0)),
        ('REC003', 'quality', (5.0, 7.0)),
        ('REC004', 'quality', (5.0, 7.0)),
        ('REC005', 'quality', (6.0, 8.0)),
        ('REC006', 'quality', (5.0, 7.0)),
        ('REC007', 'easy', (2.0, 4.0)),
        ('REC008', 'quality', (5.0, 7.0)),
        ('REC009', 'benchmark', None),
        ('REC010', 'cross', None),
    ],
)
def test_recipe_table(recipe_id, cls, rpe):
    assert classify('run', recipe_id, None) == cls
    assert expected_rpe(recipe_id, cls) == rpe


def test_kind_wins():
    assert classify('cross', 'REC003', 'tempo') == 'cross'
    assert classify('strength', None, 'Long') == 'strength'
    assert classify('mobility', None, None) == 'mobility'
    assert classify('rest', None, 'easy') == 'rest'
    assert classify('bike', None, 'easy') == 'unknown'


@pytest.mark.parametrize(
    ('intent', 'expected'),
    [
        ('Race day', 'benchmark'),
        ('5K time trial', 'benchmark'),
        ('Race-pace long run', 'benchmark'),
        ('Long run with tempo finish', 'long'),
        ('Easy long run', 'long'),
        ('LONG aerobic run', 'long'),
        ('Threshold intervals', 'quality'),
        ('Hill repeats', 'quality'),
        ('VO2 session', 'quality'),
        ('Fartlek', 'quality'),
        ('Tempo then easy', 'quality'),
        ('Quality slot — selected at first review', 'quality'),
        ('Easy run', 'easy'),
        ('Recovery jog', 'easy'),
        ('Shakeout', 'easy'),
        ('Strides only', 'unknown'),
        ('', 'unknown'),
        (None, 'unknown'),
    ],
)
def test_intent_fallback_order(intent, expected):
    assert classify('run', None, intent) == expected


def test_unknown_recipe_is_unknown():
    assert classify('run', 'REC099', 'Easy run') == 'unknown'
    assert expected_rpe('REC099', 'easy') is None


def test_class_defaults():
    assert expected_rpe(None, 'easy') == (2.0, 4.0)
    assert expected_rpe(None, 'long') == (3.0, 5.0)
    assert expected_rpe(None, 'quality') == (5.0, 8.0)
    assert expected_rpe(None, 'benchmark') is None
    assert expected_rpe(None, 'cross') is None
    assert expected_rpe(None, 'unknown') is None
    assert expected_rpe('REC009', 'benchmark') is None
    assert expected_rpe('REC001', 'quality') == (2.0, 4.0)


@pytest.mark.parametrize(
    ('cls', 'recipe_id', 'rpe', 'expected'),
    [
        ('easy', 'REC001', 6.0, 'above'),
        ('easy', 'REC001', 5.9, None),
        ('easy', 'REC001', 0.0, None),
        ('long', None, 7.0, 'above'),
        ('long', None, 6.9, None),
        ('quality', 'REC003', 9.0, 'above'),
        ('quality', 'REC003', 3.0, 'below'),
        ('quality', 'REC003', 3.1, None),
        ('quality', None, 10.0, 'above'),
        ('quality', None, 9.9, None),
        ('quality', None, 3.0, 'below'),
        ('benchmark', 'REC009', 10.0, None),
        ('cross', 'REC010', 10.0, None),
        ('unknown', None, 10.0, None),
        ('easy', 'REC001', None, None),
    ],
)
def test_rpe_mismatch(cls, recipe_id, rpe, expected):
    assert rpe_mismatch(cls, recipe_id, rpe) == expected


def test_constants():
    assert SESSION_CLASS_VERSION == 'session_class.v1'
    assert MISMATCH_MARGIN == 2.0
    assert QUALITY_CLASSES == {'quality', 'benchmark'}
    assert HARD_CLASSES == {'quality', 'long', 'benchmark'}
    assert QUALITY_RECIPES == {'REC003', 'REC004', 'REC005', 'REC006', 'REC008', 'REC009'}
    assert LONG_RECIPE == 'REC002'
    assert [recipe for recipe, cls in RECIPE_CLASS.items() if cls == 'long'] == ['REC002']



def test_spacing_config_identity_unchanged():
    from app.metrics.contract import config_hash
    from app.metrics.spacing import CONFIG

    assert config_hash(CONFIG) == '01c51faf66223ff3b228bf2bee35dd89b077036f052861e0ff89b5e03f85ab13'


def test_snapshot_classifies_recipes():
    from app.services import snapshot

    assert snapshot._classify(None) == 'unplanned'
    assert snapshot._classify('') == 'unplanned'
    assert snapshot._classify('REC002') == 'long'
    assert snapshot._classify('REC009') == 'quality'
    assert snapshot._classify('REC010') == 'easy'
    assert snapshot._classify('REC007') == 'easy'
