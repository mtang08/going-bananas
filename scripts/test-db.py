#!/usr/bin/env python3
"""Run PostgreSQL integration tests in a dedicated synthetic cluster."""

import argparse
import fcntl
import os
import secrets
import shlex
import shutil
import socket
import subprocess
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
HOST = '127.0.0.1'
APP_DB = 'garmin_test'
MIGRATION_DB = 'mvp1_migration_test'
ROLE = 'bananas_integration'
TEST_URLS = {'TEST_DATABASE_URL': APP_DB, 'MIGRATION_TEST_DATABASE_URL': MIGRATION_DB}
SYSTEM_DATABASES = {'postgres', 'template0', 'template1'}
TOOLS = Path('/opt/homebrew/opt/postgresql@17/bin')


def pg(tool, *args, env, **kwargs):
    executable = shutil.which(tool) or TOOLS / tool
    return subprocess.run([executable, *map(str, args)], env=env, check=True, text=True, **kwargs)


def psql(port, user, password, database, sql, env):
    return pg(
        'psql', '-X', '-w', '-h', HOST, '-p', port, '-U', user, '-d', database,
        '-Atc', sql, '-v', 'ON_ERROR_STOP=1', env={**env, 'PGPASSWORD': password},
        stdout=subprocess.PIPE,
    ).stdout.strip()


def url(port, user, password, database):
    userinfo = quote(user, safe='')
    if password:
        userinfo += ':' + quote(password, safe='')
    return f'postgresql+psycopg://{userinfo}@{HOST}:{port}/{database}'


def external_urls(port, env):
    connections = {}
    for variable, database in TEST_URLS.items():
        try:
            parsed = urlsplit(os.environ.get(variable, ''))
            if (
                parsed.scheme == 'postgresql+psycopg' and parsed.username
                and parsed.hostname in {HOST, 'localhost'} and parsed.port == port
                and parsed.path == '/' + database and not (parsed.query or parsed.fragment)
            ):
                connections[variable] = (unquote(parsed.username), unquote(parsed.password or ''), database)
                continue
        except ValueError:
            pass
        raise SystemExit(f'Set {variable} to a psycopg URL for {HOST}:{port}/{database}.')

    allowed_databases = SYSTEM_DATABASES | set(TEST_URLS.values())
    urls = {}
    for variable, (user, password, database) in connections.items():
        databases = set(psql(port, user, password, database, 'SELECT datname FROM pg_database', env).splitlines())
        if not set(TEST_URLS.values()) <= databases <= allowed_databases:
            raise SystemExit('The external PostgreSQL server must be dedicated to integration tests.')
        urls[variable] = url(port, user, password, database)
    return urls


def managed_urls(workspace, port, env, *, stop=False):
    cluster = workspace / 'data'
    password_file = workspace / 'password'
    log = workspace / 'postgres.log'
    if any(path.is_symlink() for path in (cluster, password_file, log)):
        raise SystemExit('The managed integration cluster cannot use symlinked paths.')

    if not password_file.is_file():
        if cluster.exists():
            raise SystemExit('Refusing to manage an existing cluster without an integration password file.')
        if stop:
            print('Managed integration PostgreSQL is not running.')
            return {}
        with socket.socket() as probe:
            probe.settimeout(1)
            if probe.connect_ex((HOST, port)) == 0:
                raise SystemExit(
                    f'Port {port} is already in use. Select a free TEST_DATABASE_PORT, '
                    'or use make test-integration-external for a dedicated test cluster.'
                )
        password = secrets.token_hex(32)
        pg(
            'initdb', '-D', cluster, '-U', ROLE, '--auth=scram-sha-256',
            '--pwfile=/dev/stdin', '--encoding=UTF8', '--locale=C',
            input=password + '\n', env=env, stdout=subprocess.DEVNULL,
        )
        password_file.write_text(password + '\n')
    else:
        password = password_file.read_text().strip()

    if not (cluster / 'PG_VERSION').is_file():
        raise SystemExit('The managed integration cluster is incomplete.')
    try:
        pg('pg_ctl', '-D', cluster, 'status', env=env, stdout=subprocess.DEVNULL)
        running = True
    except subprocess.CalledProcessError as error:
        if error.returncode != 3:
            raise
        running = False

    if not running:
        if stop:
            print('Managed integration PostgreSQL is not running.')
            return {}
        options = shlex.join(['-h', HOST, '-p', str(port), '-k', ''])
        pg('pg_ctl', '-D', cluster, '-l', log, '-o', options, '-w', 'start', env=env)
    data_directory = psql(port, ROLE, password, 'postgres', 'SHOW data_directory', env)
    if Path(data_directory).resolve() != cluster:
        raise SystemExit('Refusing to use a PostgreSQL server outside the managed integration directory.')
    if stop:
        pg('pg_ctl', '-D', cluster, '-m', 'fast', '-w', 'stop', env=env)
        return {}

    databases = set(psql(port, ROLE, password, 'postgres', 'SELECT datname FROM pg_database', env).splitlines())
    if databases - SYSTEM_DATABASES - set(TEST_URLS.values()):
        raise SystemExit('The managed PostgreSQL server must be dedicated to integration tests.')
    for database in TEST_URLS.values():
        if database not in databases:
            psql(port, ROLE, password, 'postgres', f'CREATE DATABASE {database}', env)
    print(f'Managed integration PostgreSQL is ready at {HOST}:{port}.', flush=True)
    return {variable: url(port, ROLE, password, database) for variable, database in TEST_URLS.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    native_checks = {
        'proposal': 'test_proposal_slice.py',
        'planning-contract': 'check_planning_contract.py',
        'workspace-preflight': 'check_workspace_preflight.py',
        'dashboard': 'check_dashboard.py',
        'supervisor': 'check_supervisor.py',
        'calendar-commands': 'check_calendar_commands.py',
        'planning-commands': 'check_planning_commands.py',
        'annotations': 'check_annotations.py',
        'activity-reads': 'check_activity_reads.py',
        'completion-http': 'check_completion_http.py',
        'feedback-http': 'check_feedback_http.py',
        'exception-http': 'check_exception_http.py',
        'travel-http': 'check_travel_http.py',
        'sync-http': 'check_sync_http.py',
        'phone-checkins': 'check_phone_checkins.py',
    }
    checks = {
        **native_checks,
        'provider': 'check_provider_replay.py',
        'strong': 'check_strong_import.py',
        'exception-view': 'check_exception_view.py',
        'exception-inputs': 'check_exception_inputs.py',
        'recovery': 'check_recovery.py',
        'aerobic': 'check_aerobic.py',
        'assessment': 'check_assessment_db.py',
        'gcal': 'check_gcal_replay.py',
        'provider-jobs': 'check_provider_jobs.py',
        'fit-cli': 'check_fit_cli.py',
        'workspace-migrate': 'check_workspace_migrate.py',
        'demo-seed': 'check_demo_seed.py',
        'import-export': 'check_import_export.py',
        'backup': 'check_workspace_backup.py',
        'operator-cli': 'check_operator_cli.py',
        'calendar': 'check_self_reports.py',
        'health-startup': 'check_health_startup.py',
        'rematch': 'check_rematch.py',
    }
    actions = ['start', 'stop', 'test', 'test-external', 'native', 'native-external', *checks, *(name + '-external' for name in checks)]
    parser.add_argument('action', choices=actions)
    parser.add_argument('tests', nargs='*', help='test paths or pytest node IDs relative to backend')
    args = parser.parse_args()
    action = args.action
    if args.tests and action not in {'test', 'test-external'}:
        parser.error(f'{action} does not take test selectors')

    backend = ROOT / 'backend'
    tests = args.tests or ['tests/integration', 'tests/test_ingestion_integration.py']
    if action in {'test', 'test-external'}:
        for selector in tests:
            path, separator, node = selector.partition('::')
            target = (backend / path).resolve()
            if (
                not path or selector.startswith('-') or not target.is_relative_to(backend / 'tests')
                or not target.exists() or (separator and (not node or not target.is_file()))
            ):
                parser.error(f'Invalid test selector {selector!r}. Use an existing path or node ID under backend/tests.')

    try:
        port = int(os.environ.get('TEST_DATABASE_PORT', '55439'))
        if not 1024 <= port <= 65535 or port in {5432, 55432}:
            raise ValueError
    except ValueError:
        raise SystemExit('TEST_DATABASE_PORT must be an unprivileged port other than 5432 or 55432.')

    os.umask(0o077)
    private = ROOT / 'private'
    managed = private / 'integration-postgres'
    external = private / 'integration-external'
    use_external = action.endswith('-external')
    workspace = (external if use_external else managed) / str(port)
    for path in (private, workspace.parent, workspace, workspace / 'lock', workspace / 'app'):
        if path.is_symlink():
            raise SystemExit('The integration workspace cannot use symlinked paths.')
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)

    # libpq settings can redirect an otherwise explicit database URL.
    env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    env.update(PGPASSFILE=os.devnull, PGCONNECT_TIMEOUT='3')
    with (workspace / 'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(f'An integration database command is already running on port {port} in this checkout.')

        if use_external:
            urls = external_urls(port, env)
        else:
            urls = managed_urls(workspace, port, env, stop=action == 'stop')
        if action in {'start', 'stop'}:
            return

        app_dir = workspace / 'app'
        app_dir.mkdir(exist_ok=True)
        env.update(
            urls, DATABASE_URL=urls['TEST_DATABASE_URL'], TEST_DATABASE_PORT=str(port), APP_MODE='test',
            PRIVATE_DIR=str(app_dir), UV_NO_ENV_FILE='1',
        )
        env.pop('UV_ENV_FILE', None)
        env.setdefault('UV_CACHE_DIR', str(private / 'cache' / 'uv'))
        selected = action.removesuffix('-external')
        if selected == 'native' or selected in checks:
            runners = native_checks.values() if selected == 'native' else [checks[selected]]
            for runner in runners:
                print(f'Running {runner}', flush=True)
                subprocess.run(
                    ['uv', 'run', 'python', '../scripts/rewrite/' + runner],
                    cwd=backend, env=env, check=True,
                )
            return
        subprocess.run(['uv', 'run', 'alembic', 'upgrade', 'head'], cwd=backend, env=env, check=True)
        subprocess.run(
            ['uv', 'run', 'pytest', *tests, '-m', 'integration'],
            cwd=backend, env=env, check=True,
        )


if __name__ == '__main__':
    try:
        main()
    except FileNotFoundError as error:
        raise SystemExit(f'Required command or file is missing: {error.filename}')
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode)
