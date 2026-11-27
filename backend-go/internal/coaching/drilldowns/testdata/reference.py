"""Compare the native drill-downs against the five Python query functions."""

import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

here = Path(__file__).resolve()
sys.path.insert(0, str(here.parents[5] / "backend"))
from app.api import metrics
from app.services.calendar import calendar_diff
from app.services.decision_inputs import canonical_json

url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"])
schema = url.query["search_path"]
assert (
    url.host in {"localhost", "127.0.0.1"}
    and url.database == "garmin_test"
    and re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
)
url = (
    url.set(drivername="postgresql+psycopg")
    .difference_update_query(["search_path"])
    .update_query_dict({"options": f"-csearch_path={schema}"})
)
with Session(create_engine(url)) as s:
    assert s.scalar(text("SELECT current_schema()")) == schema
    s.connection().exec_driver_sql(
        here.with_name("seed.sql")
        .read_text()
        .replace(
            "@IDENTITIES@",
            (here.parents[2] / "evidence/metric_identities.json").read_text(),
        )
    )
    now = datetime(2026, 11, 5, 12, tzinfo=UTC)
    s.info["metrics_now"] = now
    # state_at derives certainty from today's calendar; these fixture runs are already committed.
    activity = UUID(int=1)
    metric_id = s.scalar(
        text("SELECT id FROM metric_results WHERE metric_id='aerobic_efficiency'")
    )
    day = date(2026, 11, 2)
    cases = [
        [
            {"name": "calendar_diff", "from_version": 0, "to_version": 1},
            calendar_diff(s, 0, 1),
        ],
        [
            {"name": "calendar_diff", "from_version": 1, "to_version": 2},
            calendar_diff(s, 1, 2),
        ],
        [
            {"name": "calendar_diff", "from_version": 2, "to_version": 0},
            calendar_diff(s, 2, 0),
        ],
        [
            {"name": "explain_metric", "result_id": str(metric_id)},
            metrics.explain_metric(s, metric_id),
        ],
        [
            {"name": "activity_execution", "activity_id": str(activity)},
            metrics.activity_execution(s, activity),
        ],
        [
            {"name": "long_run_history", "start": str(day), "end": str(day)},
            metrics.long_run_history(s, day, day),
        ],
        [
            {"name": "recovery_nights", "start": str(day), "end": str(day)},
            metrics.recovery_nights(s, day, day),
        ],
    ]
    s.connection().exec_driver_sql(here.with_name("preview.sql").read_text())
    s.expire_all()
    cases.extend(
        [
            [
                {"name": "activity_execution", "activity_id": str(activity)},
                metrics.activity_execution(s, activity),
                True,
            ],
            [
                {"name": "long_run_history", "start": str(day), "end": str(day)},
                metrics.long_run_history(s, day, day),
                True,
            ],
        ]
    )
    print(canonical_json(cases))
