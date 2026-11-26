"""Generate the compact ordered Go proposal model from Python's schema."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))


def schema():
    from app.services.proposals.schema import ProposalDoc

    source = ProposalDoc.model_json_schema()
    models = source.pop("$defs")
    models["ProposalDoc"] = source
    from app.services.proposals.lifecycle import RevisionRequest
    from app.services.proposals.decision import DecisionRequest
    for command in (RevisionRequest, DecisionRequest):
        models[command.__name__] = command.model_json_schema()

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
                    "default", [] if rule.get("type") == "array" else None
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
    path = ROOT / "backend-go/internal/coaching/drafts/model.json"
    text = schema()
    if args.check:
        if path.read_text() != text:
            raise SystemExit(
                "proposal model differs; regenerate with scripts/rewrite/coaching/schema.py"
            )
    else:
        path.write_text(text)
