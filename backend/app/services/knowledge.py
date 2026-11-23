"""Bounded, local selection of reviewed coaching research.

This module returns evidence context. It neither decides training nor activates
the package's candidate policies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.operations import OPERATIONS

DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "running_coach_kb"
MAX_FILE_BYTES = 200_000
MAX_ROUTED_CONTEXT_CHARS = 200_000


class KnowledgeIntegrityError(ValueError):
    """The local research snapshot is incomplete or differs from its manifest."""


def _read(root: Path, rel: str, manifest: dict) -> str:
    path = PurePosixPath(rel)
    if path.is_absolute() or ".." in path.parts or str(path) != rel:
        raise KnowledgeIntegrityError("Invalid knowledge path")
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


SUPPORTED_OPERATIONS = OPERATIONS
CONDITIONAL_TOPICS = tuple(
    f"topics/{name}.md"
    for name in (
        "ptt_and_load_tolerance",
        "recovery_and_daily_adaptation",
        "hybrid_strength_and_scheduling",
        "long_runs_and_race_development",
        "aerobic_progression",
        "intensity_and_workout_methods",
        "intensity_calibration_and_testing",
        "periodization_and_training_blocks",
        "races_tapers_and_transitions",
        "travel_and_time_zones",
    )
)
POLICY_MAP: dict[str, tuple[str, ...]] = {
    "proceed_or_modify_today": ("P001", "P002", "P004", "P005", "P006", "P012", "P013", "P015", "P018"),
    "review_rolling_plan": (
        "P001",
        "P003",
        "P006",
        "P007",
        "P008",
        "P009",
        "P010",
        "P012",
        "P013",
        "P014",
        "P015",
        "P016",
        "P017",
    ),
    "select_quality_session": ("P009", "P014", "P015", "P020"),
    "review_training_block": ("P003", "P007", "P009", "P014", "P019", "P021", "P028"),
    "recalibrate_intensity": ("P010", "P015", "P020", "P021"),
    "handle_goal_or_race_change": ("P019", "P022", "P023"),
    "exception_review": (
        "P001",
        "P002",
        "P003",
        "P004",
        "P005",
        "P006",
        "P013",
        "P015",
        "P018",
        "P024",
        "P025",
        "P026",
    ),
    "post_event_review": ("P006", "P013", "P018", "P020", "P021", "P026", "P027"),
}
TOKEN_BUDGET: dict[str, int] = {
    "proceed_or_modify_today": 1800,
    "review_rolling_plan": 3000,
    "select_quality_session": 5000,
    "review_training_block": 5000,
    "recalibrate_intensity": 5000,
    "handle_goal_or_race_change": 5000,
    "exception_review": 9000,
    "post_event_review": 7000,
}
POLICY_FILES = ("policies/coaching_policy_candidates.json", "policies/periodization_policy_candidates.json")
RECIPE_FILE = "recipes/running_session_families.json"
EVIDENCE_FILES = ("references/evidence_matrix.md", "references/periodization_evidence_addendum.md")
EVIDENCE_ROW = re.compile(r"^\| (E-[A-Z]+-\d{2}) \|", re.M)
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")


@dataclass(frozen=True)
class KbExcerpt:
    path: str
    section: str | None
    record_id: str | None
    text: str

    def to_json(self) -> dict:
        result = {"path": self.path, "text": self.text}
        if self.section is not None:
            result["section"] = self.section
        elif self.record_id is not None:
            result["record_id"] = self.record_id
        return result


@dataclass(frozen=True)
class KbBundle:
    package_version: str
    excerpts: tuple[KbExcerpt, ...]
    chars: int
    approx_tokens: int
    routes: tuple[dict, ...]

    def to_json(self) -> dict:
        return {
            "package_version": self.package_version,
            "excerpts": [e.to_json() for e in self.excerpts],
            "chars": self.chars,
            "approx_tokens": self.approx_tokens,
        }


@dataclass(frozen=True)
class KbIndex:
    package_version: str
    policy_ids: frozenset[str]
    recipe_ids: frozenset[str]
    evidence_ids: frozenset[str]


def load_manifest(root: Path | None = None) -> dict:
    base = Path(root) if root is not None else DEFAULT_ROOT
    path = base / "manifest.json"
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            raise KnowledgeIntegrityError("Knowledge manifest missing or unsafe")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != "1.1"
            or manifest.get("package_name") != "running_coach_kb"
            or not isinstance(manifest.get("package_version"), str)
            or not isinstance(manifest.get("routing"), dict)
            or not isinstance(manifest.get("files"), list)
        ):
            raise KnowledgeIntegrityError("Unsupported knowledge manifest")
        seen: set[str] = set()
        for entry in manifest["files"]:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("path"), str)
                or type(entry.get("bytes")) is not int
                or entry["bytes"] < 0
                or "sha256" not in entry
                or (entry["sha256"] is not None and not isinstance(entry["sha256"], str))
            ):
                raise KnowledgeIntegrityError("Invalid manifest file records")
            rel = entry["path"]
            posix = PurePosixPath(rel)
            if posix.is_absolute() or ".." in posix.parts or str(posix) != rel or rel in seen:
                raise KnowledgeIntegrityError("Invalid knowledge path")
            seen.add(rel)
            if entry["sha256"] is not None:
                _read(base, rel, manifest)
        return manifest
    except KnowledgeIntegrityError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise KnowledgeIntegrityError("Knowledge manifest is malformed") from exc


def extract_section(text: str, heading: str, path: str) -> str:
    lines = text.split("\n")
    matches = [
        (i, match) for i, line in enumerate(lines) if (match := HEADING.match(line)) and match.group(2) == heading
    ]
    if len(matches) != 1:
        raise KnowledgeIntegrityError(f"Section not found exactly once: {path} :: {heading}")
    start, match = matches[0]
    level = len(match.group(1))
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if (following := HEADING.match(lines[i])) and len(following.group(1)) <= level
        ),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip("\n")


def _records(base: Path, manifest: dict) -> dict[str, dict[str, dict]]:
    result = {}
    try:
        for path, key, id_key in [
            *((p, "policies", "policy_id") for p in POLICY_FILES),
            (RECIPE_FILE, "recipes", "recipe_id"),
        ]:
            items = json.loads(_read(base, path, manifest))[key]
            indexed = {item[id_key]: item for item in items}
            if len(indexed) != len(items):
                raise KnowledgeIntegrityError("Duplicate knowledge record")
            result[path] = indexed
    except (KeyError, TypeError, ValueError, OSError, UnicodeError) as exc:
        raise KnowledgeIntegrityError("Invalid knowledge records") from exc
    return result


def _policy_text(p: dict) -> str:
    return (
        f"{p['policy_id']}: {p['title']}\n"
        f"Trigger: {'; '.join(p['trigger'])}\n"
        f"Suggested action: {'; '.join(p['suggested_action'])}\n"
        f"Do not apply when: {'; '.join(p['do_not_apply_when'])}\n"
        f"Rationale: {p['rationale']}\n"
        f"Evidence: {', '.join(p['evidence_ids'])}; sources: {', '.join(p['source_ids'])}\n"
        f"Certainty: {p['evidence_certainty']}; applicability: {p['athlete_applicability']}\n"
        f"Uncertainty: {p['uncertainty']}"
    )


def _record_text(path: str, record: dict) -> str:
    return _policy_text(record) if path in POLICY_FILES else json.dumps(record, ensure_ascii=False)


def _bounded(excerpts: Iterable[KbExcerpt]) -> int:
    chars = sum(len(e.text) for e in excerpts)
    if chars > MAX_ROUTED_CONTEXT_CHARS:
        raise KnowledgeIntegrityError("Selected knowledge context exceeds bound")
    return chars


def load_route(
    operation: str, *, recipe_ids: Iterable[str] = (), conditional_topics: Iterable[str] = (), root: Path | None = None
) -> KbBundle:
    if operation not in SUPPORTED_OPERATIONS:
        raise ValueError("unsupported_operation")
    topics = set(conditional_topics)
    if topics - set(CONDITIONAL_TOPICS):
        raise ValueError("unknown_conditional_topic")
    base = Path(root) if root is not None else DEFAULT_ROOT
    manifest = load_manifest(base)
    excerpts: list[KbExcerpt] = []
    try:
        for item in manifest["routing"][operation]["minimum"]:
            if not isinstance(item, dict):
                raise KnowledgeIntegrityError("Unsupported routing item")
            if "sections" in item:
                path = item["path"]
                if not isinstance(item["sections"], list) or not all(isinstance(s, str) for s in item["sections"]):
                    raise KnowledgeIntegrityError("Unsupported routing item")
                content = _read(base, path, manifest)
                excerpts.extend(
                    KbExcerpt(path, section, None, extract_section(content, section, path))
                    for section in item["sections"]
                )
            elif "state" not in item and "records" not in item:
                raise KnowledgeIntegrityError("Unsupported routing item")
        for path in CONDITIONAL_TOPICS:
            if path in topics:
                first = next((i for i, e in enumerate(excerpts) if e.path == path), len(excerpts))
                excerpts = [e for e in excerpts if e.path != path]
                excerpts.insert(first, KbExcerpt(path, None, None, _read(base, path, manifest).strip("\n")))
        records = _records(base, manifest)
        for rid in sorted(set(recipe_ids)):
            if rid not in records[RECIPE_FILE]:
                raise ValueError("unknown_recipe_id")
            excerpts.append(KbExcerpt(RECIPE_FILE, None, rid, _record_text(RECIPE_FILE, records[RECIPE_FILE][rid])))
        for pid in POLICY_MAP[operation]:
            path = next((p for p in POLICY_FILES if pid in records[p]), None)
            if path is None:
                raise KnowledgeIntegrityError("Missing policy record")
            excerpts.append(KbExcerpt(path, None, pid, _policy_text(records[path][pid])))
    except (KeyError, TypeError, OSError, UnicodeError) as exc:
        raise KnowledgeIntegrityError("Malformed knowledge routing") from exc
    chars = _bounded(excerpts)
    approx_tokens = math.ceil(chars / 4)
    if approx_tokens > TOKEN_BUDGET[operation]:
        logging.getLogger(__name__).warning(
            "kb_budget_exceeded operation=%s approx_tokens=%d budget=%d",
            operation,
            approx_tokens,
            TOKEN_BUDGET[operation],
        )
    routes: dict[str, dict] = {}
    for e in excerpts:
        key, value = ("record_ids", e.record_id) if e.record_id is not None else ("sections", e.section or "*")
        routes.setdefault(e.path, {"path": e.path, key: []})[key].append(value)
    return KbBundle(manifest["package_version"], tuple(excerpts), chars, approx_tokens, tuple(routes.values()))


def kb_index(root: Path | None = None) -> KbIndex:
    base = Path(root) if root is not None else DEFAULT_ROOT
    manifest = load_manifest(base)
    records = _records(base, manifest)
    return KbIndex(
        manifest["package_version"],
        frozenset(pid for p in POLICY_FILES for pid in records[p]),
        frozenset(records[RECIPE_FILE]),
        frozenset(eid for p in EVIDENCE_FILES for eid in EVIDENCE_ROW.findall(_read(base, p, manifest))),
    )


def verify_selection(selection: tuple[dict, ...], *, root: Path | None = None) -> dict:
    """Reconstruct saved selection, retaining its order and verifying current bytes."""
    base = Path(root) if root is not None else DEFAULT_ROOT
    manifest = load_manifest(base)
    index = kb_index(base)
    records = _records(base, manifest)
    excerpts: list[KbExcerpt] = []
    selected: dict[tuple[str, str], dict] = {}
    try:
        for item in selection:
            if not isinstance(item, dict) or set(item) not in ({"path", "sections"}, {"path", "record_ids"}):
                raise KnowledgeIntegrityError("Invalid saved knowledge selection")
            path = item["path"]
            content = _read(base, path, manifest)
            key = "sections" if "sections" in item else "record_ids"
            values = item[key]
            if not isinstance(values, list) or not values or not all(isinstance(v, str) for v in values):
                raise KnowledgeIntegrityError("Invalid saved knowledge selection")
            for value in values:
                if key == "sections":
                    section = None if value == "*" else value
                    text = content.strip("\n") if section is None else extract_section(content, section, path)
                    excerpts.append(KbExcerpt(path, section, None, text))
                else:
                    record = records[path][value]
                    excerpts.append(KbExcerpt(path, None, value, _record_text(path, record)))
                    selected[(path, value)] = {"path": path, "record_id": value, "content": record}
    except KnowledgeIntegrityError:
        raise
    except (KeyError, TypeError, ValueError, OSError, UnicodeError) as exc:
        raise KnowledgeIntegrityError("Invalid saved knowledge selection") from exc
    _bounded(excerpts)
    selected_records = tuple(selected[k] for k in sorted(selected))
    payload = {
        "manifest": manifest,
        "excerpts": [
            {"path": e.path, "section": e.section, "record_id": e.record_id, "text": e.text} for e in excerpts
        ],
        "selected_records": selected_records,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return {
        "digest": digest,
        "selection": selection,
        "selected_records": selected_records,
        "policy_ids": index.policy_ids,
        "recipe_ids": index.recipe_ids,
        "evidence_ids": index.evidence_ids,
    }
