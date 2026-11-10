"""Compare a restored acceptance backup to source without showing personal data."""
from pathlib import Path
import hashlib
import argparse
import sys
from urllib.parse import urlsplit,urlunsplit

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'backend'))
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from app.config import settings
from app.db import SessionLocal
from app.models import Activity,Checkin,PlanVersion,ProfileVersion,RawObject,RecoveryObservation,SourceRecord

parser=argparse.ArgumentParser()
parser.add_argument('--database',default='garmin_restore_test')
parser.add_argument('--private-dir',type=Path,default=root/'private/restore-validation')
args=parser.parse_args()
assert args.database.endswith('_test'), 'Only an isolated test restore may be verified'
url=urlsplit(settings.database_url)
restore_url=urlunsplit((url.scheme,url.netloc,'/'+args.database,url.query,url.fragment))
engine=create_engine(restore_url)
private=args.private_dir.resolve()
with SessionLocal() as source, Session(engine) as restored:
    for model in [Activity,Checkin,PlanVersion,ProfileVersion,RawObject,RecoveryObservation,SourceRecord]:
        expected=source.scalar(select(func.count()).select_from(model))
        actual=restored.scalar(select(func.count()).select_from(model))
        assert expected==actual,model.__tablename__
    raws=restored.scalars(select(RawObject)).all()
    for raw in raws:
        path=(private/raw.relative_path).resolve()
        assert path.is_relative_to(private.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest()==raw.sha256
print(f'Restore verified: 7 table counts match, {len(raws)} raw references and checksums intact; original database unchanged.')
