from pathlib import Path
import shutil
import sys

root=Path(__file__).resolve().parents[1]
missing=[]
for tool in ['uv','node','npm','psql','pg_dump','pg_restore']:
    found=shutil.which(tool)
    print(f'{tool}: '+('available' if found else 'missing'))
    if not found: missing.append(tool)
print('.env: '+('present (values hidden)' if (root/'.env').exists() else 'not configured'))
print('Research KB: '+('present' if (root/'running_coach_kb').exists() else 'not installed; analytics does not require it'))
sys.exit(bool(missing))
