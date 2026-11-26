"""Run the original weekly projection inside a disposable test connection."""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

here = Path(__file__).resolve().parent
sys.path.insert(0, str(here.parents[3] / "backend"))
from app.services.timezone import athlete_today
from app.services.weekly_projection import weekly_projection

url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"]).set(
    drivername="postgresql+psycopg"
)
schema = url.query["search_path"]
assert (
    url.database == "garmin_test"
    and url.host in {"127.0.0.1", "localhost"}
    and re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
)
url = url.difference_update_query(["search_path"])
with Session(
    create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
) as session:
    result = []
    for filename, times in [
        ("empty.sql", ["2030-01-07T06:30:00Z", "2030-01-07T07:00:00Z"]),
        (
            "plan.sql",
            ["2030-01-10T01:00:00Z", "2030-01-13T18:00:00Z", "2030-03-11T05:30:00Z"],
        ),
    ]:
        session.connection().exec_driver_sql((here / filename).read_text())
        for instant in times:
            now = datetime.fromisoformat(instant)
            with patch(
                "app.services.calendar.calendar_today", lambda s: athlete_today(s, now)
            ):
                result.append(
                    {
                        "fixture": filename,
                        "now": instant,
                        "projection": weekly_projection(session),
                    }
                )
    print(json.dumps(result, default=str))
