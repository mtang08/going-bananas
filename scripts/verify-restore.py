"""Compare a restored acceptance backup to source without showing personal data."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'backend'))

from app.coaching_models import CoachOutcome, CoachOutcomeEvent, CoachRecommendation  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Activity,
    Checkin,
    PlanVersion,
    ProfileVersion,
    RawObject,
    RecoveryObservation,
    SourceRecord,
)
from app.strong_models import StrongWorkoutRow  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument('--database', required=True)
parser.add_argument('--private-dir', type=Path, required=True)
args = parser.parse_args()
assert args.database.endswith('_test'), 'Only an isolated test restore may be verified'
assert settings.app_mode == 'real', 'Compare against the real source database'
url = urlsplit(settings.database_url)
restore_url = urlunsplit((url.scheme, url.netloc, '/' + args.database, url.query, url.fragment))
engine = create_engine(restore_url)
private = args.private_dir.resolve()
source_private = settings.private_dir.resolve()
models = [
    Activity, Checkin, PlanVersion, ProfileVersion, RawObject, RecoveryObservation,
    SourceRecord, StrongWorkoutRow, CoachRecommendation, CoachOutcome, CoachOutcomeEvent,
]
with SessionLocal() as source, Session(engine) as restored:
    for model in models:
        expected = source.scalar(select(func.count()).select_from(model))
        actual = restored.scalar(select(func.count()).select_from(model))
        assert expected == actual, model.__tablename__
    for model in (StrongWorkoutRow, CoachRecommendation, CoachOutcome, CoachOutcomeEvent):
        columns = [column.key for column in model.__table__.columns]
        def digest(session):
            rows = []
            for obj in session.scalars(select(model)).all():
                rows.append({name: getattr(obj, name) for name in columns})
            rows.sort(key=lambda row: str(row['id']))
            data = json.dumps(rows, sort_keys=True, default=str, separators=(',', ':')).encode()
            return hashlib.sha256(data).digest()
        assert digest(source) == digest(restored), model.__tablename__
    raws = restored.scalars(select(RawObject)).all()
    for raw in raws:
        path = (private / raw.relative_path).resolve()
        assert path.is_relative_to(private)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == raw.sha256

    research = source_private / 'research-imports'
    assert research.is_dir(), 'Source research originals missing'
    original_files = sorted(p.relative_to(source_private) for p in research.rglob('*') if p.is_file())
    assert original_files, 'No research originals found'
    for relative in original_files:
        original = source_private / relative
        copy = private / relative
        assert copy.is_file(), relative
        assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(copy.read_bytes()).digest(), relative

print(f'Restore verified: {len(models)} table counts match, {len(raws)} raw references and checksums intact, '
      f'{len(original_files)} research original files match; new table contents match; source database unchanged.')
