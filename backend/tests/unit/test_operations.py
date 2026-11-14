import re
from typing import get_args

from app.coach_v2_models import CoachProposal, CoachSnapshot
from app.services import knowledge, proposals, snapshot
from app.services.operations import OPERATIONS

NON_OPERATION_ROUTES = {"deep_evidence_audit", "evaluation"}
CHECKS = ((CoachSnapshot, "ck_coach_snapshots_operation"), (CoachProposal, "ck_coach_proposals_operation"),
          (CoachProposal, "ck_coach_proposals_escalation"))


def _check_values(model, name: str) -> set[str]:
    constraint = next(c for c in model.__table__.constraints if c.name == name)
    return set(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))


def test_operations_unique():
    assert len(OPERATIONS) == len(set(OPERATIONS)) == 8


def test_backend_sites_match_operations():
    ops = set(OPERATIONS)
    assert knowledge.SUPPORTED_OPERATIONS == OPERATIONS
    assert set(knowledge.POLICY_MAP) == ops
    assert set(knowledge.TOKEN_BUDGET) == ops
    assert set(get_args(proposals.ProposalDoc.model_fields["operation"].annotation)) == ops
    assert {snapshot.DAILY, snapshot.ROLLING, snapshot.QUALITY_OP, snapshot.BLOCK, snapshot.CALIB, snapshot.RACE,
            snapshot.EXCEPTION, snapshot.POST_EVENT} == ops


def test_manifest_routing_matches_operations():
    assert set(knowledge.load_manifest()["routing"]) - NON_OPERATION_ROUTES == set(OPERATIONS)


def test_db_checks_match_operations():
    for model, name in CHECKS:
        assert _check_values(model, name) == set(OPERATIONS), name
