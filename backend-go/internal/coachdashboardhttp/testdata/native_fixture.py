"""Keep a separately migrated synthetic schema alive while the HTTP test uses it."""

import os
import re
import sys
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import psycopg
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

repo = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(repo / "backend"), str(repo / "scripts/rewrite")]
from app.models import ProfileVersion
from app.services import calendar
from test_proposal_slice import migrated_schema

url = make_url(os.environ["DASHBOARD_TEST_DATABASE_URL"])
assert url.database == "garmin_test" and url.host in {"127.0.0.1", "localhost"}
assert re.fullmatch(r"go_parity_[a-f0-9]{32}", url.query["search_path"])
url = url.difference_update_query(["search_path"])
with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as db:
    with tempfile.TemporaryDirectory(dir=repo / "private") as tmp:
        with migrated_schema(
            db, url.set(drivername="postgresql+psycopg"), Path(tmp) / "app", "0"
        ) as env:
            engine = create_engine(
                url.set(drivername="postgresql+psycopg"),
                connect_args={"options": env["PGOPTIONS"]},
            )
            with (
                Session(engine) as s,
                patch.object(calendar, "calendar_today", lambda *_: date(2026, 11, 16)),
            ):
                s.add(
                    ProfileVersion(
                        version=1,
                        effective_at=datetime(2026, 11, 15, tzinfo=UTC),
                        timezone="America/New_York",
                        cycle_anchor=date(2026, 11, 16),
                        anchor_confirmed=True,
                        strength_days_confirmed=True,
                        scheduled_strength_days=[0, 4],
                        facts={},
                        preferences={},
                        unknowns=[],
                    )
                )
                s.flush()
                changes = []
                for day, kind in [
                    (16, "strength"),
                    (20, "strength"),
                    (23, "strength"),
                    (27, "strength"),
                    (18, "run"),
                ]:
                    fields = {
                        "local_date": date(2026, 11, day),
                        "kind": kind,
                        "intent": "Train",
                    }
                    if kind == "run":
                        fields.update(recipe_id="REC001", planned_duration_s=1800)
                    changes.append({"op": "add", "fields": fields})
                calendar.apply_edits(s, 0, changes, "Synthetic dashboard fixture")
                schema = (
                    s.connection()
                    .exec_driver_sql("select current_schema()")
                    .scalar_one()
                )
                s.commit()
            engine.dispose()
            print(f"READY {schema}", flush=True)
            sys.stdin.read()
