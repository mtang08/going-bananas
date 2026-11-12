"""Exercise the pending-only coach helper without contacting an app."""
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / '.codex/skills/going-bananas-coach'
spec = importlib.util.spec_from_file_location('coach_helper_v2', PACKAGE/'scripts/coach_app.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
SCHEMA = {'protocol':'coach_proposal.v1', 'activation':'manual', 'required_authority':'calendar'}
UID = '00000000-0000-4000-8000-000000000042'


class HelperTests(unittest.TestCase):
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
        self.assertEqual(command[:2], [str(ROOT/'scripts/with-mode'),'demo'])
        self.assertEqual(command[-4:], ['query','activity_execution','--activity-id',UID])
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(run.call_args.kwargs['cwd'], ROOT)

    def test_schema_mismatch_never_submits(self):
        with patch.object(helper, 'run_cli', return_value=(0,{**SCHEMA,'activation':'automatic'})) as run, \
             patch.object(helper, 'repo_root', return_value=ROOT), patch('sys.stderr', new_callable=io.StringIO):
            self.assertEqual(helper.main(['--mode','real','submit','--file','unused.json']), 2)
        self.assertEqual(run.call_count, 1)

    def test_private_copy_preserves_document_and_pending_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = {'schema_version':'coach_proposal.v1','snapshot_id':UID,
                'base_calendar_version':7,'changes':[{'change_id':'c1','reason':'synthetic'}]}
            source = root/'draft.json'
            source.write_text(json.dumps(document))
            with patch.object(helper, 'repo_root', return_value=root), \
                 patch.object(helper, 'run_cli', side_effect=[(0,SCHEMA),(0,{'proposal_id':UID,'status':'pending','errors':[]})]) as run, \
                 patch('sys.stdout', new_callable=io.StringIO) as output:
                self.assertEqual(helper.main(['--mode','real','submit','--file',str(source)]), 0)
            saved = Path(run.call_args.args[2][-1])
            self.assertEqual(saved.parent, root/'private/real/coach/proposals')
            self.assertEqual(json.loads(saved.read_text()), document)
            self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
            result = json.loads(output.getvalue())
            self.assertEqual(result['message'], 'Pending your review; nothing applied.')
            self.assertTrue(result['review_url'].endswith('#proposal/'+UID))
            self.assertFalse(any('decision' in str(call) for call in run.call_args_list))

    def test_stale_response_is_not_automatically_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'draft.json'
            source.write_text(json.dumps({'schema_version':'coach_proposal.v1','snapshot_id':UID}))
            with patch.object(helper, 'repo_root', return_value=root), \
                 patch.object(helper, 'run_cli', side_effect=[(0,SCHEMA),(3,{'status':'stale','errors':[]})]) as run, \
                 patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(helper.main(['--mode','real','submit','--file',str(source)]), 3)
            self.assertEqual(run.call_count, 2)

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

    def test_undo_requires_valid_head_reason_and_calendar_authority(self):
        client = helper.Client('http://localhost:8000', 'real')
        client.request = Mock(side_effect=[{'data':{'planning_authority':'calendar'}},{'mode':'real','data':{}}])
        with self.assertRaises(helper.HelperError):
            client.undo(2,1,' ')
        client.undo(2,1,'Explicit athlete request')
        self.assertEqual(client.request.call_args.args, ('POST','/calendar/rollback',
            {'expected_head':2,'to_version':1,'reason':'Explicit athlete request'}))

    def test_manifest_covers_exact_artifact_bytes(self):
        manifest = json.loads((PACKAGE/'coach-helper.manifest.json').read_text())
        self.assertEqual(manifest['activation'], 'manual')
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
