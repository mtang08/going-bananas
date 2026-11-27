"""Compare all operation routes and excerpts on empty and populated synthetic inputs."""

import hashlib
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend"))
from app.services.decision_inputs import canonical_json
from app.services.knowledge import POLICY_MAP, load_route, verify_selection
from app.services.snapshot.common import SnapshotInputs
from app.services.snapshot.topics import select_conditional_topics, select_recipe_ids

today = date(2027, 3, 14)
now = datetime(2027, 3, 14, 14, tzinfo=UTC)
inputs = SnapshotInputs(
    as_of=today,
    now=now,
    timezone="America/New_York",
    calendar_version=4,
    data_revision=2,
    cycle_anchor=None,
    anchor_confirmed=False,
    clinical_restriction=None,
)
out = []
for populated in (False, True):
    if populated:
        numeric = {"target": {"modality": "hr"}}
        inputs.sessions = [
            {
                "kind": "run",
                "local_date": today,
                "recipe_id": "REC004",
                "structure": [{"type": "repeat", "steps": [numeric]}],
            },
            {"kind": "run", "local_date": today, "recipe_id": "REC002"},
            {"kind": "run", "local_date": "2027-04-05", "recipe_id": "REC007"},
            {"kind": "strength", "local_date": "2027-03-16", "strength_slot_id": "L"},
        ]
        inputs.strength_slots = [
            {"slot_id": "L", "active": True, "lower_body_cost": "moderate"}
        ]
        inputs.anchors = [{"confidence": "low", "status": "active"}]
        inputs.checkins = [{"local_date": today, "pain_reported": True, "symptoms": []}]
        inputs.metric_results = [
            {
                "subject_type": "night",
                "subject_key": "night:2027-03-13",
                "metric_id": "recovery_multisignal_summary",
                "value": {"sleep": {"value": 15, "quality_flags": ["check"]}},
            }
        ]
        inputs.trips = [{"start_date": "2027-03-10", "end_date": None}]
        inputs.active_block = {
            "start_date": "2027-03-03",
            "review_date": "2027-04-06",
            "eligible_recipe_ids": ["REC006"],
        }
    for op in POLICY_MAP:
        topics, recipes = (
            select_conditional_topics(inputs, op),
            select_recipe_ids(inputs, op),
        )
        route = load_route(op, recipe_ids=recipes, conditional_topics=topics)
        excerpts = [e.to_json() for e in route.excerpts]
        verified = verify_selection(route.routes)
        out.append(
            {
                "operation": op,
                "inputs": asdict(inputs),
                "topics": topics,
                "recipes": recipes,
                "excerpts_sha": hashlib.sha256(
                    canonical_json(excerpts).encode()
                ).hexdigest(),
                "digest": verified["digest"],
                "chars": route.chars,
                "version": route.package_version,
            }
        )
print(canonical_json(out))
