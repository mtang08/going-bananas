import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from app.services.knowledge import DEFAULT_ROOT, KnowledgeIntegrityError, load_knowledge


def test_selective_context_order_and_metadata():
    context = load_knowledge(
        "daily", topics=["ptt_and_load_tolerance"], policy_ids=["P005"], source_ids=["S028"]
    )
    assert context.integrity_ok
    assert context.package_version == "1.1.0+privacy1"
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
    for entry in manifest["files"]:
        raw = (DEFAULT_ROOT / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]


def test_missing_and_malformed_manifest_fail_as_integrity_error(tmp_path: Path):
    with pytest.raises(KnowledgeIntegrityError):
        load_knowledge("daily", root=tmp_path)
    (tmp_path / "manifest.json").write_text("{bad json")
    with pytest.raises(KnowledgeIntegrityError):
        load_knowledge("daily", root=tmp_path)


def test_block_policy_recipe_and_source_selection_is_explicit_and_ordered():
    context = load_knowledge(
        "block", topics=["periodization_and_training_blocks"], policy_ids=["P020", "P005", "P020"],
        source_ids=["S072", "S028"], recipe_ids=["REC003", "REC001", "REC003"],
    )
    assert context.searched_through == "2026-11-11"
    assert context.selected_files == (
        "COACHING_GUIDE.md", "workflows/block_review.md", "topics/periodization_and_training_blocks.md",
        "policies/coaching_policy_candidates.json", "policies/periodization_policy_candidates.json",
        "references/source_registry.json", "recipes/running_session_families.json",
    )
    assert [p["policy_id"] for p in context.policies] == ["P020", "P005"]
    assert [s["source_id"] for s in context.sources] == ["S072", "S028"]
    assert [r["recipe_id"] for r in context.recipes] == ["REC003", "REC001"]
    assert context.recipes[0]["prerequisites"]
    assert context.recipes[0]["illustrative_doses"]
    assert '"recipe_id": "REC005"' not in context.text
    minimal = load_knowledge("daily")
    assert minimal.selected_files == ("COACHING_GUIDE.md", "workflows/daily_recommendation.md")
    assert minimal.recipes == minimal.policies == minimal.sources == ()


def test_new_records_fail_closed_and_context_remains_bounded(tmp_path: Path):
    with pytest.raises(ValueError, match="Unknown recipe"):
        load_knowledge("daily", recipe_ids=["REC999"])
    with pytest.raises(ValueError, match="Too many"):
        load_knowledge("block", recipe_ids=["REC001", "REC002", "REC003", "REC004"])
    with pytest.raises(ValueError, match="exceeds bound"):
        load_knowledge("block", topics=["periodization_and_training_blocks", "intensity_calibration_and_testing",
                                       "races_tapers_and_transitions", "hybrid_strength_and_scheduling"],
                       recipe_ids=["REC001", "REC002", "REC003"])
    shutil.copytree(DEFAULT_ROOT, tmp_path, dirs_exist_ok=True)
    recipe_path = tmp_path / "recipes/running_session_families.json"
    recipe_path.write_bytes(recipe_path.read_bytes().replace(b"Easy aerobic", b"Fake aerobic"))
    with pytest.raises(KnowledgeIntegrityError, match="hash mismatch"):
        load_knowledge("daily", recipe_ids=["REC001"], root=tmp_path)
    policy_path = tmp_path / "policies/periodization_policy_candidates.json"
    policy_path.unlink()
    with pytest.raises(KnowledgeIntegrityError, match="Missing or unsafe"):
        load_knowledge("block", policy_ids=["P019"], root=tmp_path)


def test_incremental_ids_are_unique_and_references_resolve():
    registry = json.loads((DEFAULT_ROOT / "references/source_registry.json").read_text())["sources"]
    sources = {s["source_id"] for s in registry}
    assert len(sources) == len(registry) == 72
    policies = []
    for path in sorted((DEFAULT_ROOT / "policies").glob("*.json")):
        policies.extend(json.loads(path.read_text())["policies"])
    assert len({p["policy_id"] for p in policies}) == len(policies) == 23
    recipes = json.loads((DEFAULT_ROOT / "recipes/running_session_families.json").read_text())["recipes"]
    assert len({r["recipe_id"] for r in recipes}) == len(recipes) == 10
    evidence = set()
    for rel in ("references/evidence_matrix.md", "references/periodization_evidence_addendum.md"):
        evidence.update(re.findall(r"\| (E-[A-Z]+-\d+) \|", (DEFAULT_ROOT / rel).read_text()))
    assert len(evidence) == 55

    def check_references(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "source_ids":
                    assert set(item) <= sources
                elif key == "evidence_ids":
                    assert set(item) <= evidence
                check_references(item)
        elif isinstance(value, list):
            for item in value:
                check_references(item)

    check_references(policies)
    check_references(recipes)
