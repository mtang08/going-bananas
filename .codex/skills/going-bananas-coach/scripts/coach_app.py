"""Local training snapshots and pending proposals; acceptance stays in the app."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

UTC = timezone.utc

OPERATIONS = ('proceed_or_modify_today', 'review_rolling_plan', 'review_training_block',
              'select_quality_session', 'recalibrate_intensity', 'handle_goal_or_race_change')
QUERIES = ('activity_execution', 'long_run_history', 'recovery_nights', 'calendar_diff', 'explain_metric')
MODES = ('real', 'demo', 'test')


class HelperError(Exception):
    def __init__(self, code: str, status: int = 1):
        self.code, self.status = code, status
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base_url: str, mode: str):
        url = urlsplit(base_url)
        if (mode not in MODES or url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost'}
                or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment):
            raise HelperError('invalid_local_endpoint', 2)
        self.base, self.mode = base_url.rstrip('/'), mode
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=None):
        request = Request(self.base + '/api/v1' + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Content-Type': 'application/json', 'X-Local-Request': '1'})
        with self.opener.open(request, timeout=20) as response:
            result = json.load(response)
        if not isinstance(result, dict) or result.get('mode') != self.mode:
            raise HelperError('app_mode_mismatch', 2)
        return result

    def undo(self, expected_head, target_version, reason):
        if expected_head < 1 or target_version < 0 or not reason.strip():
            raise HelperError('invalid_undo_request', 2)
        profile = self.request('GET', '/profile')
        if profile.get('data', {}).get('planning_authority') != 'calendar':
            raise HelperError('planning_upgrade_required', 2)
        return self.request('POST', '/calendar/rollback',
            {'expected_head': expected_head, 'to_version': target_version, 'reason': reason})


def repo_root(explicit: Path | None = None) -> Path:
    candidates = ([explicit] if explicit else []) + ([Path(os.environ['GB_REPO'])] if os.getenv('GB_REPO') else [])
    candidates += list(Path(__file__).resolve().parents) + [Path.home() / 'dev/going-bananas']
    for candidate in candidates:
        if (candidate / 'scripts/with-mode').is_file() and (candidate / 'backend/app/cli.py').is_file():
            return candidate.resolve()
        if explicit:
            break
    raise HelperError('repository_not_found', 2)


def run_cli(root: Path, mode: str, arguments: list[str]):
    if mode not in MODES:
        raise HelperError('invalid_mode', 2)
    command = [str(root / 'scripts/with-mode'), mode, 'uv', 'run', '--directory', str(root / 'backend'),
               'python', '-m', 'app.cli', 'coach', *arguments]
    response = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=180, check=False)
    try:
        payload = json.loads(response.stdout if response.stdout.strip() else response.stderr)
    except (ValueError, TypeError):
        raise HelperError('invalid_app_response') from None
    if not isinstance(payload, dict) or response.returncode not in (0, 1, 2, 3, 4):
        raise HelperError('invalid_app_response')
    return response.returncode, payload


def verify_protocol(root: Path, mode: str):
    code, schema = run_cli(root, mode, ['schema'])
    if code or any(schema.get(k) != value for k, value in {
            'protocol': 'coach_proposal.v1', 'activation': 'manual', 'required_authority': 'calendar'}.items()):
        raise HelperError('incompatible_coach_protocol', 2)
    return schema


def save_proposal(root: Path, mode: str, source: Path) -> Path:
    try:
        raw = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(raw, dict) or raw.get('schema_version') != 'coach_proposal.v1':
            raise ValueError()
        UUID(raw['snapshot_id'])
        json.dumps(raw, allow_nan=False)
    except (OSError, UnicodeError, ValueError, KeyError, TypeError):
        raise HelperError('invalid_proposal_file', 2) from None
    directory = root / 'private' / mode / 'coach/proposals'
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    path = directory / (stamp + '.json')
    with path.open('x', encoding='utf-8') as stream:
        path.chmod(0o600)
        json.dump(raw, stream, ensure_ascii=False, allow_nan=False)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=MODES, required=True)
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('schema')
    snapshot = sub.add_parser('snapshot')
    snapshot.add_argument('--operation', choices=OPERATIONS, required=True)
    snapshot.add_argument('--as-of')
    query = sub.add_parser('query')
    query.add_argument('name', choices=QUERIES)
    for flag in ('activity-id', 'start', 'end', 'from', 'to', 'result-id'):
        query.add_argument('--' + flag)
    submit = sub.add_parser('submit')
    submit.add_argument('--file', type=Path, required=True)
    sub.add_parser('history')
    proposal = sub.add_parser('proposal')
    proposal.add_argument('id', type=UUID)
    undo = sub.add_parser('undo')
    undo.add_argument('--expected-head', type=int, required=True)
    undo.add_argument('--target-version', type=int, required=True)
    undo.add_argument('--reason', required=True)
    args = parser.parse_args(argv)
    try:
        # Validate configured origin even for commands using the local CLI.
        client = Client(args.base_url, args.mode)
        if args.command in {'history', 'proposal', 'undo'}:
            if args.command == 'history':
                result = client.request('GET', '/calendar/versions')
            elif args.command == 'proposal':
                result = client.request('GET', f'/coach/proposals/{args.id}')
            else:
                result = client.undo(args.expected_head, args.target_version, args.reason)
            code = 0
        else:
            root = repo_root(args.repo)
            schema = verify_protocol(root, args.mode)
            if args.command == 'schema':
                result, code = schema, 0
            else:
                arguments = [args.command]
                if args.command == 'snapshot':
                    arguments += ['--operation', args.operation]
                    if args.as_of:
                        arguments += ['--as-of', args.as_of]
                elif args.command == 'query':
                    arguments.append(args.name)
                    for name in ('activity_id', 'start', 'end', 'from', 'to', 'result_id'):
                        value = getattr(args, name)
                        if value is not None:
                            arguments += ['--' + name.replace('_', '-'), value]
                else:
                    saved = save_proposal(root, args.mode, args.file)
                    arguments += ['--file', str(saved)]
                code, result = run_cli(root, args.mode, arguments)
                if args.command == 'snapshot' and code == 0:
                    meta = result.get('payload', {}).get('snapshot_meta', {})
                    if not result.get('snapshot_id') or not meta.get('source_fingerprint'):
                        raise HelperError('invalid_snapshot_response')
                if args.command == 'submit' and code == 0:
                    if result.get('status') != 'pending' or not result.get('proposal_id'):
                        raise HelperError('invalid_submission_response')
                    uid = str(UUID(result['proposal_id']))
                    result = {**result, 'message': 'Pending your review; nothing applied.',
                              'review_url': f'{client.base}/#proposal/{uid}'}
        print(json.dumps(result, default=str, ensure_ascii=False))
        return code
    except HelperError as exc:
        print(json.dumps({'error': exc.code}), file=sys.stderr)
        return exc.status
    except (HTTPError, URLError, TimeoutError, subprocess.TimeoutExpired, OSError, ValueError):
        print(json.dumps({'error': 'local_app_unavailable'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
