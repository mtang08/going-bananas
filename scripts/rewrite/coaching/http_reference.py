"""Capture synthetic public proposal views using the reference FastAPI router."""

import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.db import SessionLocal
from app.main import app
from sqlalchemy import text


def main():
    with SessionLocal() as s:
        database, schema = s.execute(
            text("SELECT current_database(),current_schema()")
        ).one()
        if (
            os.environ.get("APP_MODE") != "test"
            or database != "garmin_test"
            or not schema.startswith("go_drafts_")
        ):
            raise ValueError("requires an isolated synthetic database")
        ids = s.scalars(
            text("SELECT id FROM coach_proposals ORDER BY submitted_at,id")
        ).all()
    client = TestClient(app)
    paths = ["/api/v1/coach/proposals/active"]
    for id in ids:
        for suffix in ("", "/document", "/revisions/1"):
            paths.append(f"/api/v1/coach/proposals/{id}{suffix}")
    result = []
    for path in paths:
        r = client.get(path)
        assert r.status_code == 200, (path, r.status_code, r.text)
        result.append(dict(path=path, body=r.json()))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
