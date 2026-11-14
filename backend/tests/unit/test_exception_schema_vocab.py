from app.exception_models import ExceptionFinding, ExceptionPatch
from app.services.exceptions.vocab import CATEGORY, FINDING_STATUS, LADDER, NON_TERMINAL_FINDING, PATCH_STATUS, SEVERITY


def _in(col, vals):
    return f"{col} IN ({','.join(repr(v) for v in vals)})"


def _check(table, name):
    return next(constraint for constraint in table.constraints if constraint.name == name)


def test_exception_checks_match_vocab():
    finding_checks = {
        "ck_exception_findings_category": ("category", CATEGORY),
        "ck_exception_findings_severity": ("severity", SEVERITY),
        "ck_exception_findings_status": ("status", FINDING_STATUS),
    }
    patch_checks = {
        "ck_exception_patches_category": ("category", CATEGORY),
        "ck_exception_patches_severity": ("severity", SEVERITY),
        "ck_exception_patches_status": ("status", PATCH_STATUS),
        "ck_exception_patches_ladder_level": ("ladder_level", LADDER),
    }
    for name, (column, values) in finding_checks.items():
        assert str(_check(ExceptionFinding.__table__, name).sqltext) == _in(column, values)
    for name, (column, values) in patch_checks.items():
        assert str(_check(ExceptionPatch.__table__, name).sqltext) == _in(column, values)


def test_active_finding_index_matches_nonterminal_vocab():
    index = next(index for index in ExceptionFinding.__table__.indexes
                  if index.name == "uq_exception_findings_active")
    assert str(index.dialect_options["postgresql"]["where"]) == _in("status", NON_TERMINAL_FINDING)
