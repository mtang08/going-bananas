from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.exceptions.lifecycle import address_findings, close_finding, resolve_patch, supersede_patch

NOW = datetime(2026, 11, 16, 17, tzinfo=UTC)
P = uuid4()
PID = uuid4()


def _finding(**kwargs):
    values = {"status": "open", "closed_at": None, "close_note": None,
              "reviewed_by_proposal_id": None, "patch_id": None, "version": 1}
    values.update(kwargs)
    return SimpleNamespace(**values)


def _patch():
    return SimpleNamespace(status="open", resolved_at=None, resolved_by=None,
                           resolution_note=None, version=1, id=PID)


def test_close_finding_records_terminal_status_and_proposal():
    finding = _finding()
    close_finding(finding, "reviewed", now=NOW, proposal_id=P)
    assert (finding.status, finding.closed_at, finding.reviewed_by_proposal_id, finding.version) == (
        "reviewed", NOW, P, 2)


def test_close_finding_preserves_proposal_when_dismissing():
    finding = _finding(reviewed_by_proposal_id=P)
    close_finding(finding, "dismissed", now=NOW, note="n")
    assert finding.close_note == "n"
    assert finding.reviewed_by_proposal_id == P


def test_close_finding_rejects_nonterminal_status():
    with pytest.raises(ValueError):
        close_finding(_finding(), "open", now=NOW)


def test_address_findings_links_patch_and_increments_versions():
    findings = [_finding(), _finding()]
    address_findings(findings, SimpleNamespace(id=PID))
    assert [(f.status, f.patch_id, f.version) for f in findings] == [
        ("addressed", PID, 2), ("addressed", PID, 2)]


def test_resolve_patch_escalated_records_resolution_without_cascade():
    patch = _patch()
    resolve_patch(patch, "escalated", by="athlete", now=NOW, note="x")
    assert (patch.status, patch.resolved_at, patch.resolved_by, patch.resolution_note, patch.version) == (
        "escalated", NOW, "athlete", "x", 2)


def test_supersede_patch_records_coach_resolution():
    patch = _patch()
    supersede_patch(patch, now=NOW)
    assert (patch.status, patch.resolved_at, patch.resolved_by, patch.resolution_note, patch.version) == (
        "superseded", NOW, "coach", None, 2)
