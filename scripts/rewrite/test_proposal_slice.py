"""Exercise native proposal, planning and calendar HTTP routes through Vite and PostgreSQL."""

import os
import selectors
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url
from check_goal_commands import check_goals
from check_proposal_list import check_list, read_response
from schema_fixture import check_native_schema

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


def check_open_states(env, port):
    with psycopg.connect(env['PROPOSAL_TEST_DATABASE_URL'], options=env['PGOPTIONS'], autocommit=True) as fixture:
        for state in ('stale', 'invalid', 'pending'):
            updated = fixture.execute(
                "UPDATE coach_proposals SET status = %s WHERE id = %s AND skill_version = 'fixture'",
                (state, '00000000-0000-0000-0000-000000000033'),
            )
            if updated.rowcount != 1:
                raise SystemExit('Expected the single synthetic draft')
            status, response = read_response(int(port), '?status=open')
            if status != 200 or [row['status'] for row in response['data']['items']] != [state]:
                raise SystemExit(f'Open filter omitted or misreported the {state} draft')
            status, active = read_response(int(port), '', '/api/v1/coach/proposals/active')
            assert status == 200 and active['data']['proposal']['status'] == state
            print(f'PASS proposal list and active lookup include {state}', flush=True)


def check_planning_lists(env, port):
    def check(path, query, count):
        status, response = read_response(int(port), query, path)
        if count is None:
            assert status == 422 and response['error']['fields'][0]['field'] == 'query.limit'
            return None
        items = response['data']['items']
        assert status == 200 and len(items) == count
        return items

    versions = '/api/v1/calendar/versions'
    check(versions, '', 0)
    check('/api/v1/goals', '', 0)
    with psycopg.connect(env['PROPOSAL_TEST_DATABASE_URL'], options=env['PGOPTIONS'], autocommit=True) as fixture:
        fixture.execute("""
            INSERT INTO calendar_versions (id, number, parent_number, kind, actor, reason,
                proposal_id, restored_from_number, created_at)
            SELECT md5(i::text)::uuid, i, nullif(i - 1, 0), 'manual_edit', 'user',
                CASE WHEN i > 1 THEN 'synthetic edit' END,
                CASE WHEN i = 51 THEN '00000000-0000-0000-0000-000000000033'::uuid END,
                nullif(i - 1, 0), '2026-01-02T00:00:00.123400Z'::timestamptz + i * interval '1 day'
            FROM generate_series(1, 51) i
        """)
        for query, expected in [('', 50), ('?limit=1', 1), ('?limit=50', 50), ('?limit=0', None),
                                ('?limit=51', None), ('?limit=', None), ('?limit=bad', None),
                                ('?limit=2.0', 2), ('?limit=1_0', 10), ('?limit=bad&limit=3', 3),
                                ('?limit=3&limit=bad', None)]:
            items = check(versions, query, expected)
            if items:
                assert [item['number'] for item in items] == list(range(51, 51 - expected, -1))
                assert items[0]['proposal_id'] == '00000000-0000-0000-0000-000000000033'
                assert items[0]['block_version_id'] is None
                assert items[0]['created_at'].endswith('.123400+05:45')
        fixture.execute("DELETE FROM calendar_versions WHERE reason = 'synthetic edit' OR number = 1")
        fixture.execute("""
            INSERT INTO goals (id, text, horizon, priority, status, version) VALUES
              (md5('g1')::uuid, 'history one', 'season', 2, 'paused', 3),
              (md5('g2')::uuid, 'history two', 'long_term', 2, 'active', 1),
              (md5('g3')::uuid, 'history three', 'season', 1, 'done', 2)
        """)
        assert [goal['text'] for goal in check('/api/v1/goals', '', 3)] == [
            'history three', 'history one', 'history two',
        ]
        fixture.execute("DELETE FROM goals WHERE id IN (md5('g1')::uuid, md5('g2')::uuid, md5('g3')::uuid)")
    print('PASS calendar history limits, nulls, timestamps, validation and goal list ordering', flush=True)


@contextmanager
def native_server(env, app_binary):
    with listener(
        [app_binary, 'serve', '-repo', ROOT, '-listen', '127.0.0.1:0'],
        env=env, stdout=subprocess.PIPE, text=True,
    ) as process:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=15):
                raise SystemExit('Go listener did not start in time')
            address = process.stdout.readline().strip()
        host, _, port = address.partition(':')
        if host != '127.0.0.1' or not port.isdigit():
            raise SystemExit('Go listener did not report its local port')
        yield port


@contextmanager
def migrated_schema(db, url, directory, vite_port, *, app_binary=None):
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
        command = [app_binary] if app_binary else ['go', 'run', './cmd/going-bananas']
        subprocess.run([*command, 'migrate'], cwd=MODULE, env=env, check=True)
        yield env
    finally:
        db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def exercise(db, url, scratch):
    from check_calendar_views import check_calendar_views

    subprocess.run(['go', 'test', '-count=1', './cmd/going-bananas', '-run', 'TestApplicationRoutes'],
                   cwd=MODULE, check=True)
    app_binary = scratch / 'going-bananas'
    subprocess.run(['go', 'build', '-o', app_binary, './cmd/going-bananas'], cwd=MODULE, check=True)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        vite_port = str(reservation.getsockname()[1])
        with migrated_schema(db, url, scratch / 'ui', vite_port, app_binary=app_binary) as env:
            schema = env['PGOPTIONS'].split()[0].removeprefix('-csearch_path=')
            check_native_schema(MODULE, schema, env)
            subprocess.run(['psql', '-Xq', '-1', '-v', 'ON_ERROR_STOP=1', '-f',
                            BACKEND / 'tests/fixtures/proposal-list.sql'], env=env, check=True)
            subprocess.run(['go', 'test', '-count=1', '-race', './internal/proposals', './internal/goals'],
                           cwd=MODULE, env=env, check=True)
            with native_server(env, app_binary) as port:
                check_list(int(port))
                check_open_states(env, port)
                check_planning_lists(env, port)
                reservation.close()
                subprocess.run(['node', ROOT / 'scripts/rewrite/proposal-home.mjs', port], cwd=ROOT, env=env, check=True)
                check_calendar_views(env, port)

    with migrated_schema(db, url, scratch / 'goals', vite_port, app_binary=app_binary) as env:
        with native_server(env, app_binary) as port:
            check_goals(port, env)


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
