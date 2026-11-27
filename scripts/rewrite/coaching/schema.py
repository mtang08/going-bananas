"""Generate the compact ordered Go proposal model from Python's schema."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))


def schema(calendar=False, planning=False):
    from app.services.proposals.schema import ProposalDoc

    source = ProposalDoc.model_json_schema()
    models = source.pop("$defs")
    models["ProposalDoc"] = source
    from app.services.proposals.decision import DecisionRequest
    from app.services.proposals.lifecycle import RevisionRequest

    for command in (RevisionRequest, DecisionRequest):
        models[command.__name__] = command.model_json_schema()

    if calendar or planning:
        from app.api.anchors import AnchorInput
        from app.api.calendar import BootstrapInput, EditsInput, RollbackInput

        commands = (BootstrapInput, EditsInput, RollbackInput, AnchorInput)
        if planning:
            from app.api.core import ProfileInput, RunningInterruptionInput
            from app.api.planning import (
                BenchmarkActivityInput,
                EventInput,
                EventOrder,
                EventPatch,
                RoutineInput,
            )
            from app.domain.athlete_facts import RunningRestriction

            commands = (
                EventInput,
                EventPatch,
                EventOrder,
                RoutineInput,
                BenchmarkActivityInput,
                ProfileInput,
                RunningInterruptionInput,
                RunningRestriction,
            )
        models = {}
        for command in commands:
            shape = command.model_json_schema()
            models.update(shape.pop("$defs", {}))
            models[command.__name__] = shape

    def clean(shape):
        value = {k: v for k, v in shape.items() if k not in {"title", "description"}}
        if "$ref" in value:
            return {"ref": value["$ref"].split("/")[-1]}
        if "anyOf" in value:
            value["anyOf"] = [clean(x) for x in value["anyOf"]]
        if "items" in value:
            value["items"] = clean(value["items"])
        return value

    result = {}
    for name, obj in models.items():
        fields = []
        for field, shape in obj["properties"].items():
            rule = clean(shape)
            value = {"name": field, "shape": rule}
            if field not in obj.get("required", []):
                value["default"] = rule.pop(
                    "default",
                    {"array": [], "object": {}}.get(rule.get("type"))
                    if planning
                    else ([] if rule.get("type") == "array" else None),
                )
            fields.append(value)
        result[name] = fields
    return (
        json.dumps(result, ensure_ascii=False, separators=(",", ":"), indent=1) + "\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, text in [
        (ROOT / "backend-go/internal/coaching/drafts/model.json", schema()),
        (ROOT / "backend-go/internal/calendarhttp/model.json", schema(calendar=True)),
        (ROOT / "backend-go/internal/planninghttp/model.json", schema(planning=True)),
    ]:
        if args.check:
            if path.read_text() != text:
                raise SystemExit(
                    "proposal model differs; regenerate with scripts/rewrite/coaching/schema.py"
                )
        else:
            path.write_text(text)
