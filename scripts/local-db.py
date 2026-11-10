#!/usr/bin/env python3
"""Create/start a private project PostgreSQL cluster, preserving existing settings."""
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
private = root / 'private'
private.mkdir(exist_ok=True, mode=0o700)
cluster = private / 'postgres'
env_file = root / '.env'
content = env_file.read_text() if env_file.exists() else ''
existing = {}
for line in content.splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        k, v = line.split('=', 1)
        existing[k.strip()] = v.strip().strip('\"').strip("'")
password = existing.get('POSTGRES_PASSWORD') or secrets.token_urlsafe(32)
settings = {
    'POSTGRES_PASSWORD': password,
    'DATABASE_URL': f'postgresql+psycopg://garmin:{password}@127.0.0.1:55432/garmin_demo',
    'TEST_DATABASE_URL': f'postgresql+psycopg://garmin:{password}@127.0.0.1:55432/garmin_test',
    'APP_MODE': 'demo',
    'PRIVATE_DIR': str(private),
}
with env_file.open('a') as f:
    if content and not content.endswith('\n'):
        f.write('\n')
    for key, value in settings.items():
        if key not in existing:
            f.write(f'{key}={value}\n')
env_file.chmod(0o600)

def exe(name):
    path = shutil.which(name)
    if path:
        return path
    candidate = Path('/opt/homebrew/opt/postgresql@17/bin') / name
    if candidate.exists():
        return str(candidate)
    raise SystemExit(f'{name} not found: install PostgreSQL 17 or use Compose.')

def run(name, *args, **kwargs):
    return subprocess.run([exe(name), *map(str,args)], check=True, **kwargs)

if len(sys.argv)>1 and sys.argv[1]=='stop':
    run('pg_ctl', '-D', cluster, '-m', 'fast', 'stop')
    raise SystemExit(0)
if not (cluster/'PG_VERSION').exists():
    pwfile = private/'initdb-password'
    pwfile.write_text(password)
    pwfile.chmod(0o600)
    try:
        run('initdb', '-D', cluster, '-U', 'garmin', '--auth-local=trust', '--auth-host=scram-sha-256', f'--pwfile={pwfile}', '--encoding=UTF8', '--locale=C')
    finally:
        pwfile.unlink(missing_ok=True)
    with (cluster/'postgresql.conf').open('a') as f:
        f.write("\nlisten_addresses = '127.0.0.1'\nport = 55432\nunix_socket_directories = '"+str(private).replace("'","''")+"'\n")
status = subprocess.run([exe('pg_ctl'), '-D', str(cluster), 'status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if status.returncode:
    run('pg_ctl', '-D', cluster, '-l', private/'postgres.log', 'start')
for name in ('garmin_demo','garmin_test','garmin_real'):
    result=run('psql','-h',private,'-p','55432','-U','garmin','-d','postgres','-Atc',f"SELECT 1 FROM pg_database WHERE datname = '{name}'",capture_output=True,text=True)
    if not result.stdout.strip():
        run('createdb','-h',private,'-p','55432','-U','garmin',name)
print('Project PostgreSQL ready on 127.0.0.1:55432; demo/test/real databases are separate.')
