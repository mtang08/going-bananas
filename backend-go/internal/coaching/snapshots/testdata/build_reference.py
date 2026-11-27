"""Exercise the Python builder on exactly the same prepared evidence as the Go builder."""

import os
import re
import sys
from contextlib import ExitStack
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend"))
from app.coach_v2_models import CoachSnapshot
from app.services.decision_inputs import canonical_json
from app.services.snapshot.build import build_snapshot

url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"]).set(
    drivername="postgresql+psycopg"
)
schema = url.query["search_path"]
assert (
    url.database == "garmin_test"
    and url.host in {"localhost", "127.0.0.1"}
    and re.fullmatch(r"go_parity_[0-9a-f]{32}", schema)
)
engine = create_engine(
    url.difference_update_query(["search_path"]).update_query_dict(
        {"options": f"-csearch_path={schema} -cTimeZone=UTC"}
    )
)
native = sys.argv[1] == "--native"
ops = sys.argv[2:] if native else sys.argv[1:]
with Session(engine) as s, ExitStack() as patches:
    if not native:
        for function in (
            "app.metrics.refresh.ensure_windows",
            "app.metrics.refresh.ensure_nights",
            "app.services.exceptions.detector.run_detection",
        ):
            patches.enter_context(patch(function))
    assert s.scalar(text("SELECT current_schema()")) == schema
    for op in ops:
        packet = build_snapshot(
            s, op, date(2030, 1, 9), now=datetime(2030, 1, 9, 18, 30, tzinfo=UTC)
        )
        row = s.get(CoachSnapshot, packet.pop("snapshot_id"))
        print(
            canonical_json(
                {
                    "packet": packet,
                    "payload_canonical": canonical_json(packet["payload"]),
                    "payload_sha256": row.payload_sha256,
                    "source_versions": row.source_versions,
                }
            )
        )
        if native:
            s.commit()
        else:
            s.rollback()
