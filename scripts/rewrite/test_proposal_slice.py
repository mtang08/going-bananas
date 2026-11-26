"""Compare migrated Go routes to FastAPI and exercise their UI through Vite."""

import os
import selectors
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from http.client import HTTPConnection
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from compare_goals import compare_goals
from compare_proposals import read_response

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'backend'
MODULE = ROOT / 'backend-go'


@contextmanager
def listener(*args, **kwargs):
    process = subprocess.Popen(*args, **kwargs)
    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdout:
            process.stdout.close()


def wait_ready(port, process):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and process.poll() is None:
        client = HTTPConnection('127.0.0.1', port, timeout=0.5)
        try:
            client.request('GET', '/api/v1/health/ready')
            if client.getresponse().status == 200:
                return
        except OSError:
            pass
        finally:
            client.close()
        time.sleep(0.05)
    raise SystemExit('Python reference API did not become ready')


def check_open_states(env, ports):
    with psycopg.connect(env['PROPOSAL_TEST_DATABASE_URL'], options=env['PGOPTIONS'], autocommit=True) as fixture:
        for state in ('stale', 'invalid', 'pending'):
            updated = fixture.execute(
                "UPDATE coach_proposals SET status = %s WHERE id = %s AND skill_version = 'fixture'",
                (state, '00000000-0000-0000-0000-000000000033'),
            )
            if updated.rowcount != 1:
                raise SystemExit('Expected the single synthetic draft')
            python, go = (read_response(int(port), '?status=open') for port in ports)
            if python != go or go[0] != 200 or [row['status'] for row in go[1]['data']['items']] != [state]:
                raise SystemExit(f'Open filter omitted or misreported the {state} draft')
            print(f'PASS open filter includes {state}', flush=True)


@contextmanager
def servers(python_env, go_env, app_binary):
    with ExitStack() as stack:
        sock = stack.enter_context(socket.socket())
        sock.bind(('127.0.0.1', 0))
        sock.listen()
        python_port = str(sock.getsockname()[1])
        py = stack.enter_context(listener(
            [sys.executable, '-m', 'uvicorn', 'app.main:app', '--fd', str(sock.fileno()),
             '--no-access-log', '--log-level', 'error'],
            env={**python_env, 'APP_PORT': python_port}, cwd=BACKEND, pass_fds=(sock.fileno(),),
        ))
        wait_ready(int(python_port), py)
        go = stack.enter_context(listener(
            [app_binary, 'serve', '-listen', '127.0.0.1:0'], env=go_env,
            stdout=subprocess.PIPE, text=True,
        ))
        with selectors.DefaultSelector() as selector:
            selector.register(go.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=15):
                raise SystemExit('Go listener did not start in time')
            address = go.stdout.readline().strip()
        host, _, go_port = address.partition(':')
        if host != '127.0.0.1' or not go_port.isdigit():
            raise SystemExit('Go listener did not report its local port')
        yield python_port, go_port


@contextmanager
def migrated_schema(db, url, directory, vite_port):
    schema = 'go_parity_' + uuid4().hex
    pg_url = url.set(drivername='postgresql').render_as_string(hide_password=False)
    env = dict(
        os.environ, PRIVATE_DIR=str(directory), VITE_PORT=vite_port,
        DATABASE_URL=url.render_as_string(hide_password=False),
        PROPOSAL_TEST_DATABASE_URL=pg_url, GOAL_TEST_DATABASE_URL=pg_url,
        PGHOST=url.host, PGPORT=str(url.port), PGDATABASE=url.database, PGUSER=url.username,
        PGPASSWORD=url.password or '', PGOPTIONS=f'-csearch_path={schema} -cTimeZone=Asia/Kathmandu',
    )
    directory.mkdir()
    db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    try:
        subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND, env=env, check=True)
        yield env
    finally:
        db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def exercise(db, url, scratch):
    app_binary = scratch / 'going-bananas'
    subprocess.run(['go', 'build', '-o', app_binary, './cmd/going-bananas'], cwd=MODULE, check=True)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        vite_port = str(reservation.getsockname()[1])
        with migrated_schema(db, url, scratch / 'ui', vite_port) as env:
            subprocess.run([sys.executable, 'sql/snapshot.py', '--check'], cwd=MODULE, env=env, check=True)
            subprocess.run(['psql', '-Xq', '-1', '-v', 'ON_ERROR_STOP=1', '-f',
                            BACKEND / 'tests/fixtures/proposal-list.sql'], env=env, check=True)
            subprocess.run(['go', 'test', '-count=1', '-race', './internal/proposals', './internal/goals'],
                           cwd=MODULE, env=env, check=True)
            with servers(env, env, app_binary) as ports:
                subprocess.run([sys.executable, ROOT / 'scripts/rewrite/compare_proposals.py', *ports], check=True)
                check_open_states(env, ports)
                reservation.close()
                subprocess.run(['node', ROOT / 'scripts/rewrite/proposal-home.mjs', *ports], cwd=ROOT, env=env, check=True)

    # Each implementation must apply the same command against its own starting state.
    with migrated_schema(db, url, scratch / 'reference', vite_port) as reference, \
            migrated_schema(db, url, scratch / 'candidate', vite_port) as candidate:
        with servers(reference, candidate, app_binary) as ports:
            compare_goals(*ports, reference, candidate)


def main():
    # scripts/test-db.py also validates exclusive use of a dedicated test cluster.
    url = make_url(os.environ['TEST_DATABASE_URL'])
    if (os.environ.get('APP_MODE') != 'test' or url.database != 'garmin_test'
            or url.host not in {'127.0.0.1', 'localhost'}
            or str(url.port) != os.environ.get('TEST_DATABASE_PORT') or url.query
            or os.environ.get('DATABASE_URL') != os.environ['TEST_DATABASE_URL']):
        raise SystemExit('Use make test-proposal-go with the isolated PostgreSQL test runner')
    pg_url = url.set(drivername='postgresql').render_as_string(hide_password=False)
    with psycopg.connect(pg_url, autocommit=True) as db:
        with tempfile.TemporaryDirectory(dir=ROOT / 'private', prefix='go-parity-') as directory:
            exercise(db, url, Path(directory))


if __name__ == '__main__':
    main()
