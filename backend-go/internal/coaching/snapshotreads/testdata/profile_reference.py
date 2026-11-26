"""Generate snapshot metadata references without changing the shared synthetic dataset."""

import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / "backend"))

from app.db import get_revision
from app.domain.athlete_facts import clinical_restriction, running_restriction
from app.models import ProfileVersion
from app.read.calendar import head_version
from app.services.decision_inputs import canonical_json
from app.services.profile import current_profile
from app.services.timezone import athlete_tz

as_of = date(2026, 11, 1)
limit = {
    "starts_on": "2026-10-01",
    "review_on": "2026-11-01",
    "no_quality": "yes",
    "source": " Coach ",
}
cases = [
    None,
    {
        "clinical_restriction": "  Avoid hills  ",
        "clinician_restriction": "unused",
        "running_restriction": limit,
    },
    {
        "clinical_restriction": "uNkNoWn",
        "clinician_restriction": "  Easy only ",
        "clinical_restriction_active": True,
        "running_restriction": dict(
            limit, ends_on="2026-10-31", max_duration_s=1200, wording=" Short runs. "
        ),
    },
    {"clinical_restriction": "none", "clinical_restriction_active": "present"},
    {"clinical_restriction": False, "clinical_restriction_active": []},
    {
        "running_restriction": {
            "starts_on": 0,
            "ends_on": "2026-11-01T00:00:00+01:00",
            "max_distance_m": 1000,
            "source": "test",
        }
    },
    {"running_restriction": {"starts_on": "2026-10-20", "source": "test"}},
]
url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"]).set(
    drivername="postgresql+psycopg"
)
assert url.database == "garmin_test" and url.host in {"localhost", "127.0.0.1"}
schema = url.query["search_path"]
assert re.fullmatch(r"go_parity_[a-f0-9]{32}", schema)
url = url.difference_update_query(["search_path"]).update_query_dict(
    {"options": f"-csearch_path={schema}"}
)
out = []
with Session(create_engine(url)) as s:
    assert s.scalar(text("select current_schema()")) == schema
    for name in ("profile_versions", "app_state"):
        s.execute(
            text(f"CREATE TEMP TABLE {name} AS SELECT * FROM {name} WITH NO DATA")
        )
    for version, facts in enumerate(cases):
        if version:
            if version == 1:
                s.execute(
                    text(
                        "INSERT INTO app_state (id,data_revision,calendar_head_version) VALUES (1,19,4)"
                    )
                )
            s.add(
                ProfileVersion(
                    version=version,
                    timezone="America/Denver",
                    cycle_anchor=as_of,
                    anchor_confirmed=True,
                    facts=facts,
                    effective_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
            s.flush()
        p = current_profile(s)
        try:
            r = running_restriction(p.facts) if p else None
            view = {
                "profile_version": p.version if p else 0,
                "timezone": athlete_tz(s).key,
                "cycle_anchor": p.cycle_anchor if p else None,
                "anchor_confirmed": bool(p and p.anchor_confirmed),
                "clinical_restriction": clinical_restriction(p.facts) if p else None,
                "running_restriction": r.snapshot_data(as_of) if r else None,
                "calendar_version": head_version(s),
                "data_revision": get_revision(s),
            }
        except ValueError:
            view = None
        out.append({"facts": facts, "expected": view})
print(canonical_json(out))
