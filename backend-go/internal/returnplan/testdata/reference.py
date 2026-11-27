"""Reference the Python return-plan reader in temporary tables on the synthetic database."""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend"))
from app.services.decision_inputs import canonical_json
from app.services.running_interruption import return_view

url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"])
schema = url.query["search_path"]
assert url.host in {"localhost", "127.0.0.1"} and url.database == "garmin_test"
assert re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
url = (
    url.set(drivername="postgresql+psycopg")
    .difference_update_query(["search_path"])
    .update_query_dict({"options": f"-csearch_path={schema}"})
)
episode = {"starts_on": "2026-11-01", "return_on": "2026-11-13", "reason": "travel"}
limit = {
    "starts_on": "2026-11-16",
    "ends_on": "2026-11-16",
    "source": "Athlete",
    "max_duration_s": 1800,
}
cases = [
    ("2026-11-01", {}),
    ("2026-10-31", {"running_interruption": episode}),
    ("2026-11-06", {"running_interruption": episode, "running_restriction": limit}),
    (
        "2026-11-16",
        {"running_interruption": episode, "clinical_restriction": "Clinical limit"},
    ),
    (
        "2026-11-16",
        {
            "running_interruption": {
                "starts_on": "2026-11-01",
                "review_on": "2026-11-16",
                "reason": "other",
            }
        },
    ),
    ("2026-11-21", {"running_interruption": episode}),
    (
        "2026-12-01",
        {
            "running_interruption": {
                "starts_on": "2026-12-01",
                "return_on": "2026-12-02",
                "reason": "schedule",
            }
        },
    ),
]
with Session(create_engine(url)) as session:
    assert session.scalar(text("SELECT current_schema()")) == schema
    session.connection().exec_driver_sql(
        Path(__file__).with_name("seed.sql").read_text()
    )
    output = []
    for as_of, facts in cases:
        session.execute(
            text("UPDATE profile_versions SET facts=cast(:facts AS jsonb)"),
            {"facts": json.dumps(facts)},
        )
        session.expire_all()
        output.append(
            {
                "day": as_of,
                "facts": facts,
                "expected": return_view(session, date.fromisoformat(as_of)),
            }
        )
    print(canonical_json(output))
