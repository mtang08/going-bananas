import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from app.services.knowledge import (
    CONDITIONAL_TOPICS,
    DEFAULT_ROOT,
    POLICY_MAP,
    SUPPORTED_OPERATIONS,
    KnowledgeIntegrityError,
    extract_section,
    kb_index,
    load_manifest,
    load_route,
    verify_selection,
)


def test_manifest_covers_all_imported_files():
    manifest = json.loads((DEFAULT_ROOT / "manifest.json").read_text())
    listed = {entry["path"] for entry in manifest["files"]}
    actual = {
        str(path.relative_to(DEFAULT_ROOT))
        for path in DEFAULT_ROOT.rglob("*")
        if path.is_file() and path.name != "AGENTS.md"
    }
    assert actual - {"manifest.json"} == listed
    assert "athlete_context.md" not in listed
    for entry in manifest["files"]:
        raw = (DEFAULT_ROOT / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]


def test_incremental_ids_are_unique_and_references_resolve():
    registry = json.loads((DEFAULT_ROOT / "references/source_registry.json").read_text())["sources"]
    sources = {s["source_id"] for s in registry}
    assert len(sources) == len(registry) == 72
    policies = []
    for path in sorted((DEFAULT_ROOT / "policies").glob("*.json")):
        policies.extend(json.loads(path.read_text())["policies"])
    assert len({p["policy_id"] for p in policies}) == len(policies) == 28
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


@pytest.fixture
def tmp_kb(tmp_path):
    return Path(shutil.copytree(DEFAULT_ROOT, tmp_path / "kb"))


def test_overlay_matches_manifest():
    manifest = load_manifest()
    assert manifest["schema_version"] == "1.1"
    assert manifest["package_version"] == "1.2.0+privacy1"
    assert len(manifest["files"]) == 33
    assert manifest["baseline_revision"]["public_privacy_transform_preserved"] is True


def test_research_intake_is_not_runtime_evidence():
    for operation in SUPPORTED_OPERATIONS:
        bundle = load_route(operation)
        assert all(entry.path != 'research/coaching_web_intake.md' for entry in bundle.excerpts)


def test_extract_section_bounds():
    text = (DEFAULT_ROOT / "COACHING_GUIDE.md").read_text()
    selected = extract_section(text, "3. Decision hierarchy", "guide")
    assert selected.startswith("## 3. Decision hierarchy") and len(selected) == 1170
    assert "## 4." not in selected
    sample = "# A\nx\n## B\ny\n### C\nz\n## D\nw"
    assert extract_section(sample, "B", "sample") == "## B\ny\n### C\nz"
    assert extract_section(sample, "C", "sample") == "### C\nz"
    for text, heading in [(sample, "Q"), ("## B\n## B", "B")]:
        with pytest.raises(KnowledgeIntegrityError):
            extract_section(text, heading, "sample")


@pytest.mark.parametrize("operation,count,chars", list(zip(
    SUPPORTED_OPERATIONS, (6, 7, 9, 14, 9, 11, 14, 14), (6090, 8399, 10423, 19139, 8645, 14462, 15492, 12750), strict=True,
)))
def test_route_minimum_sections(operation, count, chars):
    bundle = load_route(operation)
    sections = [e for e in bundle.excerpts if e.section is not None]
    assert len(sections) == count
    assert sum(len(e.text) for e in sections) == chars
    assert tuple(e.record_id for e in bundle.excerpts if e.record_id) == POLICY_MAP[operation]
    verified = verify_selection(bundle.routes)
    assert len(verified["digest"]) == 64
    assert verified == verify_selection(bundle.routes)
    assert verified["selection"] == bundle.routes
    assert len(verified["selected_records"]) == len(POLICY_MAP[operation])


def test_daily_bundle_totals(caplog):
    bundle = load_route("proceed_or_modify_today")
    assert (bundle.chars, bundle.approx_tokens, len(bundle.excerpts)) == (15752, 3938, 15)
    assert (bundle.excerpts[0].path, bundle.excerpts[0].section) == ("COACHING_GUIDE.md", "3. Decision hierarchy")
    assert bundle.excerpts[-1].record_id == "P018"
    assert "kb_budget_exceeded" in caplog.text
    assert set(bundle.to_json()) == {"package_version", "excerpts", "chars", "approx_tokens"}


def test_conditional_topic_replaces_sections():
    path = "topics/intensity_and_workout_methods.md"
    bundle = load_route("select_quality_session", conditional_topics=[path, path])
    matches = [e for e in bundle.excerpts if e.path == path]
    assert len(matches) == 1 and matches[0].section is None
    assert len(matches[0].text) == 12243 and bundle.excerpts[4] == matches[0]
    assert set(matches[0].to_json()) == {"path", "text"}
    assert {"path": path, "sections": ["*"]} in bundle.routes
    verify_selection(bundle.routes)


def test_recipe_records():
    bundle = load_route("select_quality_session", recipe_ids=["REC003", "REC001", "REC003"])
    recipes = [e for e in bundle.excerpts if e.record_id and e.record_id.startswith("REC")]
    assert [e.record_id for e in recipes] == ["REC001", "REC003"]
    all_recipes = json.loads((DEFAULT_ROOT / "recipes/running_session_families.json").read_text())["recipes"]
    for e in recipes:
        record = next(r for r in all_recipes if r["recipe_id"] == e.record_id)
        assert e.text == json.dumps(record, ensure_ascii=False)
        assert set(e.to_json()) == {"path", "record_id", "text"}
    verified = verify_selection(bundle.routes)
    assert any(r["record_id"] == "REC001" and r["content"]["recipe_id"] == "REC001"
               for r in verified["selected_records"])


def test_p011_never_routed():
    for op in SUPPORTED_OPERATIONS:
        assert "P011" not in POLICY_MAP[op]
        assert all(e.record_id != "P011" for e in load_route(op).excerpts)


@pytest.mark.parametrize("kwargs,message", [
    ({"operation": "deep_evidence_audit"}, "unsupported_operation"),
    ({"operation": "proceed_or_modify_today", "recipe_ids": ["REC011"]}, "unknown_recipe_id"),
    ({"operation": "proceed_or_modify_today", "conditional_topics": ["topics/fueling_and_energy_availability.md"]},
     "unknown_conditional_topic"),
])
def test_invalid_inputs(kwargs, message):
    with pytest.raises(ValueError, match=message):
        load_route(**kwargs)


def _edit_manifest(root, edit):
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    edit(manifest)
    path.write_text(json.dumps(manifest))


def test_manifest_1_0_rejected(tmp_kb):
    _edit_manifest(tmp_kb, lambda m: m.update(schema_version="1.0"))
    with pytest.raises(KnowledgeIntegrityError):
        load_route("proceed_or_modify_today", root=tmp_kb)


def test_sha_mismatch_integrity_error(tmp_kb):
    path = tmp_kb / "workflows/weekly_review.md"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(KnowledgeIntegrityError):
        load_route("proceed_or_modify_today", root=tmp_kb)


def test_missing_heading_integrity_error(tmp_kb):
    _edit_manifest(tmp_kb, lambda m: m["routing"]["proceed_or_modify_today"]["minimum"][1].update(sections=["Nope"]))
    with pytest.raises(KnowledgeIntegrityError):
        load_route("proceed_or_modify_today", root=tmp_kb)


@pytest.mark.parametrize("symlink", [False, True])
def test_path_traversal_rejected(tmp_kb, tmp_path, symlink):
    if symlink:
        path = tmp_kb / "COACHING_GUIDE.md"
        outside = tmp_path / "outside.md"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    else:
        _edit_manifest(tmp_kb, lambda m: m["files"].append({"path": "../outside.md", "bytes": 1, "sha256": "0" * 64}))
    with pytest.raises(KnowledgeIntegrityError):
        load_route("proceed_or_modify_today", root=tmp_kb)


@pytest.mark.parametrize("contents", [None, "{bad json", "[]"])
def test_manifest_missing_or_malformed(tmp_kb, contents):
    path = tmp_kb / "manifest.json"
    path.unlink() if contents is None else path.write_text(contents)
    with pytest.raises(KnowledgeIntegrityError):
        load_route("proceed_or_modify_today", root=tmp_kb)


def test_kb_index():
    index = kb_index()
    assert len(index.policy_ids) == 28 and {"P011", "P023", "P028"} <= index.policy_ids
    assert index.recipe_ids == {f"REC{i:03}" for i in range(1, 11)}
    assert len(index.evidence_ids) == 55 and {"E-AER-01", "E-PER-02"} <= index.evidence_ids


def test_saved_selection_verifies_exact_content_and_order(tmp_kb):
    bundle = load_route("select_quality_session", recipe_ids=["REC001"], root=tmp_kb)
    before = verify_selection(bundle.routes, root=tmp_kb)
    assert before["digest"] != verify_selection(tuple(reversed(bundle.routes)), root=tmp_kb)["digest"]
    path = tmp_kb / "recipes/running_session_families.json"
    document = json.loads(path.read_text())
    document["recipes"][0]["title"] += " revised"
    path.write_text(json.dumps(document))
    with pytest.raises(KnowledgeIntegrityError):
        verify_selection(bundle.routes, root=tmp_kb)
    def update(m):
        entry = next(e for e in m["files"] if e["path"] == "recipes/running_session_families.json")
        entry.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    _edit_manifest(tmp_kb, update)
    after = verify_selection(bundle.routes, root=tmp_kb)
    assert before["digest"] != after["digest"]
    assert before["selected_records"] != after["selected_records"]


@pytest.mark.parametrize("selection", [
    ({"path": "../athlete.md", "sections": ["*"]},),
    ({"path": "COACHING_GUIDE.md", "sections": ["absent"]},),
    ({"path": "recipes/running_session_families.json", "record_ids": ["REC999"]},),
    ({"path": "COACHING_GUIDE.md", "record_ids": ["P001"]},),
    ({"path": "COACHING_GUIDE.md", "sections": "*"},),
])
def test_invalid_saved_selection(selection):
    with pytest.raises(KnowledgeIntegrityError):
        verify_selection(selection)


def test_routed_context_accepts_largest_valid_selection_without_truncation():
    from app.services.knowledge import MAX_ROUTED_CONTEXT_CHARS

    recipes = sorted(kb_index().recipe_ids)
    bundles = [load_route(operation, recipe_ids=recipes, conditional_topics=CONDITIONAL_TOPICS)
               for operation in SUPPORTED_OPERATIONS]
    assert max(bundle.chars for bundle in bundles) < MAX_ROUTED_CONTEXT_CHARS
    for bundle in bundles:
        verified = verify_selection(tuple(bundle.routes))
        assert verified["selection"] == tuple(bundle.routes)
        assert len(bundle.excerpts) > 0


def test_routed_context_hard_limit_never_truncates(monkeypatch):
    from app.services import knowledge

    monkeypatch.setattr(knowledge, "MAX_ROUTED_CONTEXT_CHARS", 1)
    with pytest.raises(KnowledgeIntegrityError, match="exceeds bound"):
        load_route("review_training_block", conditional_topics=CONDITIONAL_TOPICS)
    with pytest.raises(KnowledgeIntegrityError, match="exceeds bound"):
        verify_selection(({"path": "COACHING_GUIDE.md", "sections": ["*"] * 20},))



def test_adaptive_coaching_routes_resolve_exactly_once():
    manifest = load_manifest()
    for operation in ("exception_review", "post_event_review"):
        for item in manifest["routing"][operation]["minimum"]:
            if "sections" in item:
                text = (DEFAULT_ROOT / item["path"]).read_text()
                for heading in item["sections"]:
                    assert extract_section(text, heading, item["path"]).startswith("## " + heading)
    policy = (DEFAULT_ROOT / "adaptive_coaching/exception_policy.md").read_text()
    assert extract_section(policy, "Worked examples", "policy")
    block = manifest["routing"]["review_training_block"]["minimum"]
    assert sum(item.get("path") == "adaptive_coaching/race_and_benchmark_policy.md" for item in block) == 1


@pytest.mark.parametrize("operation", ["exception_review", "post_event_review"])
def test_new_review_routes_within_budget(operation, caplog):
    from app.services.knowledge import TOKEN_BUDGET

    bundle = load_route(operation)
    assert bundle.approx_tokens <= TOKEN_BUDGET[operation]
    assert "kb_budget_exceeded" not in caplog.text
    assert {"P011", "P019"}.isdisjoint(POLICY_MAP[operation])
    assert POLICY_MAP["review_training_block"][-1] == "P028"
    assert {e.path for e in bundle.excerpts if e.section} >= {"COACHING_GUIDE.md", "adaptive_coaching/exception_policy.md"}
