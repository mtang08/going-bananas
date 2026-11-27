"""Exercise the pending-only coach helper without contacting an app."""
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path(os.environ.get('GB_COACH_SKILL_TEST_PACKAGE', ROOT / '.codex/skills/going-bananas-coach'))
spec = importlib.util.spec_from_file_location('coach_helper_v2', PACKAGE/'scripts/coach_app.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
SCHEMA = {'protocol':'coach_proposal.v2', 'activation':'manual', 'required_authority':'calendar'}
UID = '00000000-0000-4000-8000-000000000042'


class HelperTests(unittest.TestCase):
    def test_read_only_refuses_submit_and_undo_before_access(self):
        commands = [['submit', '--file', 'unused.json'],
                    ['revise', UID, '--expected-revision', '1', '--reason', 'Update', '--file', 'unused.json'],
                    ['undo', '--expected-head', '2', '--target-version', '1', '--reason', 'test']]
        for command in commands:
            with self.subTest(command=command), patch.object(helper, 'run_cli') as cli, \
                 patch.object(helper.Client, 'request') as request, \
                 patch('sys.stderr', new_callable=io.StringIO) as output:
                self.assertEqual(helper.main(['--mode', 'real', '--read-only', *command]), 2)
                self.assertEqual(json.loads(output.getvalue())['error'], 'read_only_command_required')
                cli.assert_not_called()
                request.assert_not_called()

    def test_saved_response_is_complete_private_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = {'snapshot_id': UID, 'payload': {'long_text': 'evidence' * 10000}}
            first = helper.save_response(root, 'real', 'snapshot', result)
            second = helper.save_response(root, 'real', 'snapshot', result)
            self.assertNotEqual(first['response_file'], second['response_file'])
            self.assertNotIn('payload', first)
            self.assertEqual(first['snapshot_id'], UID)
            for saved in (first, second):
                path = Path(saved['response_file'])
                self.assertEqual(path.parent, root / 'private/real/coach/responses')
                self.assertEqual(json.loads(path.read_text()), result)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_read_only_snapshot_can_save_full_response(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = {'snapshot_id': UID, 'payload': {'snapshot_meta': {'source_fingerprint': 'a' * 64}}}
            with patch.object(helper, 'repo_root', return_value=root), \
                 patch.object(helper, 'run_cli', side_effect=[(0, SCHEMA), (0, result)]), \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(helper.main(['--mode', 'real', '--read-only', 'snapshot',
                    '--operation', 'review_rolling_plan', '--save-response']), 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(json.loads(Path(summary['response_file']).read_text()), result)

    def test_loopback_only_and_modes(self):
        for url in ['https://localhost', 'http://example.com', 'http://localhost@evil.test',
                    'http://localhost/path', 'http://localhost?x=1', 'http://localhost#x']:
            with self.subTest(url=url), self.assertRaises(helper.HelperError):
                helper.Client(url, 'real')
        with self.assertRaises(helper.HelperError):
            helper.Client('http://localhost:8000', 'unknown')

    def test_mode_mismatch_and_timeout(self):
        client = helper.Client('http://localhost:8000', 'real')
        response = Mock()
        response.__enter__ = Mock(return_value=io.BytesIO(b'{"mode":"demo","data":{}}'))
        response.__exit__ = Mock(return_value=False)
        client.opener.open = Mock(return_value=response)
        with self.assertRaises(helper.HelperError):
            client.request('GET', '/profile')
        self.assertEqual(client.opener.open.call_args.kwargs['timeout'], 20)

    def test_subprocess_uses_exact_mode_and_argument_array(self):
        with patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=0,stdout='{"ok":true}',stderr='')) as run:
            code, result = helper.run_cli(ROOT, 'demo', ['query','activity_execution','--activity-id',UID])
        self.assertEqual(code, 0)
        self.assertTrue(result['ok'])
        command = run.call_args.args[0]
        self.assertEqual(command[:3], [str(ROOT/'scripts/with-mode'),'demo',str(ROOT/'scripts/coach-cli')])
        self.assertEqual(command[-4:], ['query','activity_execution','--activity-id',UID])
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['cwd'], ROOT)

    def test_helper_passes_real_mode_to_runner(self):
        with patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=0,stdout='{}',stderr='')) as run:
            helper.run_cli(ROOT, 'real', ['schema'])
        self.assertEqual(run.call_args.args[0], [str(ROOT/'scripts/with-mode'), 'real', str(ROOT/'scripts/coach-cli'), 'schema'])

    def test_explicit_repo_requires_native_coach_entrypoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markers = ('scripts/with-mode', 'backend/app/cli.py', 'backend-go/go.mod')
            for path in markers:
                marker = root/path
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.touch()
            with self.assertRaises(helper.HelperError):
                helper.repo_root(root)
            (root/'scripts/coach-cli').touch()
            (root/'backend/app/cli.py').unlink()
            self.assertEqual(helper.repo_root(root), root.resolve())

    def test_native_coach_preserves_workspace_inside_disposable_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root/'scripts'
            scripts.mkdir()
            for name in ('with-mode', 'env.sh', 'coach-cli', 'backend-cli'):
                shutil.copy2(ROOT/'scripts'/name, scripts/name)
            # The stand-in reports its command and destination without connecting.
            hooks = root/'shell-functions'
            bin_dir = root/'bin'
            bin_dir.mkdir()
            hooks.write_text(f'export PATH="{bin_dir}:$PATH"\n')
            go = bin_dir/'go'
            go.write_text("""#!/bin/bash
while [[ "$1" != "-o" ]]; do shift; done
echo '#!/bin/bash' > "$2"
echo 'echo "$* $APP_MODE $DATABASE_URL $PRIVATE_DIR"' >> "$2"
chmod +x "$2"
""")
            go.chmod(0o700)
            (root/'.env').write_text(
                f'APP_MODE=demo\nDATABASE_URL=postgresql://fixture/config_demo\nPRIVATE_DIR={root}/configured\n'
            )
            for mode in ('real', 'test', 'demo'):
                with self.subTest(mode=mode):
                    dest = f'postgresql://fixture/selected_{mode}'
                    private = str(root/'selected')
                    env = {'PATH': os.environ['PATH'], 'APP_MODE':mode, 'PRIVATE_DIR':private,
                           'DATABASE_URL':dest, 'BASH_ENV':str(hooks)}
                    result = subprocess.run([scripts/'with-mode', mode, scripts/'coach-cli', 'schema'],
                                            env=env, capture_output=True, text=True, check=True)
                    self.assertEqual(result.stdout.strip(), f'coach schema {mode} {dest} {private}')

    def test_schema_mismatch_never_submits(self):
        with patch.object(helper, 'run_cli', return_value=(0,{**SCHEMA,'activation':'automatic'})) as run, \
             patch.object(helper, 'repo_root', return_value=ROOT), patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(helper.main(['--mode','real','submit','--file','unused.json']), 2)
        self.assertEqual(run.call_count, 1)

    def test_private_copy_preserves_document_and_pending_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = {'schema_version':'coach_proposal.v2','snapshot_id':UID,
                'base_calendar_version':7,'changes':[{'change_id':'c1','reason':'synthetic'}]}
            source = root/'draft.json'
            source.write_text(json.dumps(document))
            with patch.object(helper, 'repo_root', return_value=root), \
                 patch.object(helper, 'run_cli', side_effect=[(0,SCHEMA),(0,{'proposal_id':UID,'revision':1,'status':'pending','errors':[]})]) as run, \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(helper.main(['--mode','real','submit','--file',str(source)]), 0)
            saved = Path(run.call_args.args[2][-1])
            self.assertEqual(saved.parent, root/'private/real/coach/proposals')
            self.assertEqual(json.loads(saved.read_text()), document)
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            result = json.loads(output.getvalue())
            self.assertEqual(result['message'], 'Pending your review; nothing applied.')
            self.assertTrue(result['review_url'].endswith('#proposal/'+UID))
            self.assertEqual(result['revision'], 1)
            self.assertFalse(any('decision' in str(call) for call in run.call_args_list))

    def test_stale_response_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'draft.json'
            source.write_text(json.dumps({'schema_version':'coach_proposal.v2','snapshot_id':UID}))
            with patch.object(helper, 'repo_root', return_value=root), \
                 patch.object(helper, 'run_cli', side_effect=[(0,SCHEMA),(3,{'status':'stale','errors':[]})]) as run, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(helper.main(['--mode','real','submit','--file',str(source)]), 3)
            self.assertEqual(run.call_count, 2)

    def test_revision_uses_same_review_link_and_private_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'draft.json'
            document = {'schema_version':'coach_proposal.v2','snapshot_id':UID}
            source.write_text(json.dumps(document))
            response = {'proposal_id':UID,'revision':2,'status':'pending','errors':[]}
            with patch.object(helper, 'repo_root', return_value=root), \
                 patch.object(helper, 'run_cli', side_effect=[(0,SCHEMA),(0,response)]) as run, \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(helper.main(['--mode','real','revise',UID,'--expected-revision','1',
                    '--reason','Adjust timing','--file',str(source)]), 0)
            args = run.call_args.args[2]
            self.assertEqual(args[:6], ['revise',UID,'--expected-revision','1','--reason','Adjust timing'])
            self.assertEqual(json.loads(Path(args[-1]).read_text()), document)
            result = json.loads(output.getvalue())
            self.assertEqual(result['revision'], 2)
            self.assertTrue(result['review_url'].endswith('#proposal/'+UID))

    def test_proposal_document_routes(self):
        for extra, endpoint in [([],f'/coach/proposals/{UID}'),
                                (['--document'],f'/coach/proposals/{UID}/document'),
                                (['--document','--revision','2'],f'/coach/proposals/{UID}/revisions/2')]:
            with self.subTest(extra=extra), patch.object(helper.Client, 'request',
                    return_value={'mode':'real','data':{}}) as request, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(helper.main(['--mode','real','--read-only','proposal',UID,*extra]), 0)
            self.assertEqual(request.call_args.args, ('GET',endpoint))

    def test_active_proposal_is_read_only_get(self):
        envelope = {'mode':'real','data':{'proposal':None}}
        with patch.object(helper.Client, 'request', return_value=envelope) as request, \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(helper.main(['--mode','real','--read-only','active-proposal']), 0)
        request.assert_called_once_with('GET','/coach/proposals/active')
        self.assertEqual(json.loads(output.getvalue()), envelope)

    def test_exceptions_is_read_only_get(self):
        for extra, endpoint in [([], '/exceptions?include=active'), (['--include', 'recent'], '/exceptions?include=recent')]:
            with self.subTest(extra=extra), patch.object(helper.Client, 'request',
                    return_value={'mode': 'real', 'data': {}}) as request, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(helper.main(['--mode', 'real', '--read-only', 'exceptions', *extra]), 0)
            request.assert_called_once_with('GET', endpoint)

    def test_new_review_operations_pass_through(self):
        self.assertEqual(helper.OPERATIONS[-2:], ('exception_review', 'post_event_review'))
        payload = {'snapshot_id': UID, 'payload': {'snapshot_meta': {'source_fingerprint': 'a' * 64}}}
        for operation in ('exception_review', 'post_event_review'):
            with self.subTest(operation=operation), patch.object(helper, 'repo_root', return_value=ROOT), \
                 patch.object(helper, 'run_cli', side_effect=[(0, SCHEMA), (0, payload)]) as cli, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(helper.main(['--mode', 'real', '--read-only', 'snapshot', '--operation', operation]), 0)
            self.assertEqual(cli.call_args.args[2], ['snapshot', '--operation', operation])

    def test_snapshot_requires_source_linkage(self):
        for payload, expected in [({'snapshot_id':UID,'payload':{}},1),
                ({'snapshot_id':UID,'payload':{'snapshot_meta':{'source_fingerprint':'a'*64}}},0)]:
            with patch.object(helper, 'repo_root', return_value=ROOT), \
                 patch.object(helper, 'run_cli', side_effect=[(0,SCHEMA),(0,payload)]), \
                 patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(helper.main(['--mode','real','snapshot','--operation','review_rolling_plan']), expected)

    def test_malformed_response_is_sanitized(self):
        with patch.object(helper.subprocess, 'run', return_value=SimpleNamespace(returncode=1,stdout='',stderr='secret database URL')):
            with self.assertRaisesRegex(helper.HelperError, '^invalid_app_response$'):
                helper.run_cli(ROOT, 'real', ['snapshot'])

    def test_undo_requires_valid_head_and_reason(self):
        client = helper.Client('http://localhost:8000', 'real')
        client.request = Mock(return_value={'mode':'real','data':{}})
        with self.assertRaises(helper.HelperError):
            client.undo(2,1,' ')
        client.undo(2,1,'Explicit athlete request')
        self.assertEqual(client.request.call_args.args, ('POST','/calendar/rollback',
            {'expected_head':2,'to_version':1,'reason':'Explicit athlete request'}))

    def test_v1_protocol_and_document_are_rejected(self):
        old_schema = dict(SCHEMA, protocol='coach_proposal.v1')
        cases = [('schema', old_schema, 'coach_proposal.v2'), ('document', SCHEMA, 'coach_proposal.v1')]
        for name, schema, version in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root/'draft.json'
                source.write_text(json.dumps({'schema_version':version,'snapshot_id':UID}))
                with patch.object(helper, 'repo_root', return_value=root), \
                     patch.object(helper, 'run_cli', return_value=(0,schema)) as run, patch('sys.stderr', new_callable=io.StringIO):
                    self.assertEqual(helper.main(['--mode','real','submit','--file',str(source)]), 2)
                self.assertEqual(run.call_count, 1)

    def test_manifest_covers_exact_artifact_bytes(self):
        manifest = json.loads((PACKAGE/'coach-helper.manifest.json').read_text())
        self.assertEqual(manifest['activation'], 'manual')
        self.assertEqual(manifest['artifact_version'], 'going-bananas-coach.MVP-1.8')
        names = []
        for entry in manifest['files']:
            path = PACKAGE/entry['path']
            self.assertTrue(path.resolve().is_relative_to(PACKAGE.resolve()))
            self.assertFalse(path.is_symlink())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry['sha256'])
            names.append(entry['path'])
        self.assertEqual(names, sorted(names))
        self.assertIn('SKILL.md', names)
        self.assertIn('scripts/coach_app.py', names)


if __name__ == '__main__':
    unittest.main()
