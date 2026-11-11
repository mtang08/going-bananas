import json
from pathlib import Path

import pytest

from app.services.knowledge import DEFAULT_ROOT, KnowledgeIntegrityError, load_knowledge


def test_selective_context_order_and_metadata():
    context = load_knowledge(
        "daily", topics=["ptt_and_load_tolerance"], policy_ids=["P005"], source_ids=["S028"]
    )
    assert context.integrity_ok
    assert context.package_version == "1.0.0+privacy1"
    assert context.selected_files == (
        "COACHING_GUIDE.md",
        "workflows/daily_recommendation.md",
        "topics/ptt_and_load_tolerance.md",
        "policies/coaching_policy_candidates.json",
        "references/source_registry.json",
    )
    assert context.text.index("# COACHING_GUIDE.md") < context.text.index("# workflows/daily_recommendation.md")
    assert context.text.index("# workflows/daily_recommendation.md") < context.text.index("# topics/ptt_and_load_tolerance.md")
    assert "Candidate policies (reviewable, not executable rules)" in context.text
    assert context.policies[0]["policy_id"] == "P005"
    assert context.sources[0]["source_id"] == "S028"
    assert "athlete_context.md" not in context.selected_files


def test_unknown_selection_and_tampering_fail_closed(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown or excessive"):
        load_knowledge("daily", topics=["../athlete_context"])
    with pytest.raises(ValueError, match="Unknown policy"):
        load_knowledge("daily", policy_ids=["P999"])
    with pytest.raises(ValueError, match="Unknown source"):
        load_knowledge("weekly", source_ids=["S999"])
    (tmp_path / "manifest.json").write_bytes((DEFAULT_ROOT / "manifest.json").read_bytes())
    (tmp_path / "COACHING_GUIDE.md").write_text("tampered")
    with pytest.raises(KnowledgeIntegrityError):
        load_knowledge("daily", root=tmp_path)


def test_manifest_covers_all_imported_files():
    manifest = json.loads((DEFAULT_ROOT / "manifest.json").read_text())
    listed = {entry["path"] for entry in manifest["files"]}
    actual = {str(path.relative_to(DEFAULT_ROOT)) for path in DEFAULT_ROOT.rglob("*") if path.is_file()}
    assert actual - {"manifest.json"} == listed
    assert "athlete_context.md" not in listed


def test_missing_and_malformed_manifest_fail_as_integrity_error(tmp_path: Path):
    with pytest.raises(KnowledgeIntegrityError):
        load_knowledge("daily", root=tmp_path)
    (tmp_path / "manifest.json").write_text("{bad json")
    with pytest.raises(KnowledgeIntegrityError):
        load_knowledge("daily", root=tmp_path)
