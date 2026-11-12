"""Bounded, local selection of reviewed coaching research.

This module returns evidence context. It neither decides training nor activates
the package's candidate policies.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "running_coach_kb"
MAX_FILE_BYTES = 100_000
MAX_CONTEXT_CHARS = 70_000
WORKFLOWS = {
    "daily": "workflows/daily_recommendation.md",
    "weekly": "workflows/weekly_review.md",
    "block": "workflows/block_review.md",
}


class KnowledgeIntegrityError(ValueError):
    """The local research snapshot is incomplete or differs from its manifest."""


@dataclass(frozen=True)
class KnowledgeContext:
    text: str
    package_version: str
    searched_through: str
    selected_files: tuple[str, ...]
    integrity_ok: bool
    policies: tuple[dict, ...]
    sources: tuple[dict, ...]
    recipes: tuple[dict, ...] = ()


def _read(root: Path, rel: str, manifest: dict) -> str:
    path = PurePosixPath(rel)
    if path.is_absolute() or ".." in path.parts or str(path) != rel:
        raise ValueError("Invalid knowledge path")
    entry = next((item for item in manifest["files"] if item["path"] == rel), None)
    if entry is None or not entry.get("sha256"):
        raise KnowledgeIntegrityError(f"File absent from manifest: {rel}")
    target = root.joinpath(*path.parts)
    if not target.is_file() or target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise KnowledgeIntegrityError(f"Missing or unsafe knowledge file: {rel}")
    raw = target.read_bytes()
    if len(raw) > MAX_FILE_BYTES or len(raw) != entry["bytes"]:
        raise KnowledgeIntegrityError(f"Knowledge file size mismatch: {rel}")
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise KnowledgeIntegrityError(f"Knowledge file hash mismatch: {rel}")
    return raw.decode("utf-8")


def load_knowledge(
    workflow: Literal["daily", "weekly", "block"],
    topics: Iterable[str] = (),
    policy_ids: Iterable[str] = (),
    source_ids: Iterable[str] = (),
    *,
    recipe_ids: Iterable[str] = (),
    root: Path | None = None,
) -> KnowledgeContext:
    """Return selected prose in guide → workflow → topic → policy/source order.

    Topic names are file stems. Unknown IDs fail closed. The dated athlete
    snapshot, full report, and raw source files are never loaded implicitly.
    """
    if workflow not in WORKFLOWS:
        raise ValueError(f"Unknown workflow: {workflow}")
    base = Path(root) if root is not None else DEFAULT_ROOT
    manifest_path = base / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink() or manifest_path.stat().st_size > MAX_FILE_BYTES:
        raise KnowledgeIntegrityError("Knowledge manifest missing or unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
            raise ValueError("Invalid manifest structure")
        if any(
            not isinstance(entry, dict)
            or not isinstance(entry.get("path"), str)
            or not isinstance(entry.get("sha256"), str)
            or not isinstance(entry.get("bytes"), int)
            for entry in manifest["files"]
        ):
            raise ValueError("Invalid manifest file records")
        if not isinstance(manifest.get("package_version"), str) or not isinstance(manifest.get("searched_through"), str):
            raise ValueError("Invalid manifest metadata")
    except (OSError, UnicodeError, ValueError) as exc:
        raise KnowledgeIntegrityError("Knowledge manifest is malformed") from exc
    if manifest.get("schema_version") not in {"1.0", "1.1"} or manifest.get("package_name") != "running_coach_kb":
        raise KnowledgeIntegrityError("Unsupported knowledge manifest")
    available = {p.removeprefix("topics/").removesuffix(".md") for p in (f["path"] for f in manifest["files"]) if p.startswith("topics/") and p.endswith(".md")}
    chosen_topics = tuple(dict.fromkeys(topics))
    if len(chosen_topics) > 4 or any(topic not in available for topic in chosen_topics):
        raise ValueError("Unknown or excessive knowledge topics")
    wanted_policies = tuple(dict.fromkeys(policy_ids))
    wanted_sources = tuple(dict.fromkeys(source_ids))
    wanted_recipes = tuple(dict.fromkeys(recipe_ids))
    if len(wanted_policies) > 8 or len(wanted_sources) > 12 or len(wanted_recipes) > 3:
        raise ValueError("Too many knowledge records")
    files = ["COACHING_GUIDE.md", WORKFLOWS[workflow], *(f"topics/{topic}.md" for topic in chosen_topics)]
    sections = [f"# {rel}\n\n{_read(base, rel, manifest)}" for rel in files]
    policies: tuple[dict, ...] = ()
    sources: tuple[dict, ...] = ()
    recipes: tuple[dict, ...] = ()
    if wanted_policies:
        records = {}
        policy_files = ["policies/coaching_policy_candidates.json"]
        extension = "policies/periodization_policy_candidates.json"
        if any(entry["path"] == extension for entry in manifest["files"]):
            policy_files.append(extension)
        for policy_file in policy_files:
            data = json.loads(_read(base, policy_file, manifest))
            file_records = {p["policy_id"]: p for p in data["policies"]}
            if any(pid in file_records for pid in wanted_policies):
                files.append(policy_file)
            records.update(file_records)
            if all(pid in records for pid in wanted_policies):
                break
        if any(pid not in records for pid in wanted_policies):
            raise ValueError("Unknown policy ID")
        policies = tuple(records[pid] for pid in wanted_policies)
        sections.append("# Candidate policies (reviewable, not executable rules)\n\n" + "\n\n".join(
            f"## {p['policy_id']}: {p['title']}\n"
            f"Trigger: {'; '.join(p['trigger'])}\n"
            f"Suggested action: {'; '.join(p['suggested_action'])}\n"
            f"Do not apply when: {'; '.join(p['do_not_apply_when'])}\n"
            f"Rationale: {p['rationale']}\n"
            f"Evidence: {', '.join(p['evidence_ids'])}; sources: {', '.join(p['source_ids'])}\n"
            f"Certainty: {p['evidence_certainty']}; applicability: {p['athlete_applicability']}\n"
            f"Uncertainty: {p['uncertainty']}" for p in policies
        ))
    if wanted_sources:
        source_file = "references/source_registry.json"
        data = json.loads(_read(base, source_file, manifest))
        records = {s["source_id"]: s for s in data["sources"]}
        if any(sid not in records for sid in wanted_sources):
            raise ValueError("Unknown source ID")
        sources = tuple(records[sid] for sid in wanted_sources)
        files.append(source_file)
        sections.append("# Selected source references\n\n" + "\n\n".join(
            f"{s['source_id']}: {s['citation']} Access: {s['access_level']}. {s.get('notes', '')}" for s in sources
        ))
    if wanted_recipes:
        recipe_file = "recipes/running_session_families.json"
        data = json.loads(_read(base, recipe_file, manifest))
        records = {recipe["recipe_id"]: recipe for recipe in data["recipes"]}
        if any(rid not in records for rid in wanted_recipes):
            raise ValueError("Unknown recipe ID")
        recipes = tuple(records[rid] for rid in wanted_recipes)
        files.append(recipe_file)
        sections.append("# Selected session recipes (examples, not personalized prescriptions)\n\n" +
                        "\n\n".join(json.dumps(recipe, ensure_ascii=False, indent=2) for recipe in recipes))
    result = "\n\n".join(sections)
    if len(result) > MAX_CONTEXT_CHARS:
        raise ValueError("Selected knowledge context exceeds bound")
    return KnowledgeContext(result, manifest["package_version"], manifest["searched_through"], tuple(files), True,
                            policies, sources, recipes)
