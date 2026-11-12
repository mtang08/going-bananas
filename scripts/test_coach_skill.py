"""Synthetic verification of the skill helper; never connects to an app."""
import copy
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError

HELPER = Path(__file__).resolve().parents[1] / "skills/going-bananas-coach/scripts/coach_app.py"
spec = importlib.util.spec_from_file_location("coach_app", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class CoachClientTests(unittest.TestCase):
    def setUp(self):
        self.client = helper.Client("http://127.0.0.1:8000", "real")
        self.profile = {
            "version": 7, "timezone": "America/New_York", "cycle_anchor": "2026-11-10",
            "anchor_confirmed": True, "strength_schedule_mode": "alternating",
            "strength_week_a_start": "2026-11-09", "strength_week_a_days": [0, 4],
            "strength_week_b_days": [1, 5], "mobility_week_a_days": [2],
            "mobility_week_b_days": [3], "mobility_optional_days": [6],
            "facts": {"existing": {"confirmed": True}}, "preferences": {"units": "mi"},
            "unknowns": ["weight"],
        }
        self.entry = {"id": "60a36d67-b0d8-4a57-87d5-4b697da7eedf", "kind": "preference",
                      "recorded_at": "2026-11-11T08:00:00-05:00",
                      "content": {"training": "Preserve the agreed schedule"}}

    def mock_profile(self):
        self.client.verify_mode = Mock(return_value={"mode": "real", "data": copy.deepcopy(self.profile)})
        self.client.request = Mock(return_value={"mode": "real", "data": {}})

    def test_memory_preserves_alternating_schedule_and_unrelated_profile(self):
        self.mock_profile()
        self.client.remember(self.entry)
        method, path, body = self.client.request.call_args.args
        self.assertEqual((method, path, body["expected_version"]), ("PUT", "/profile", 7))
        self.assertNotIn("version", body)
        for key, value in self.profile.items():
            if key not in {"version", "facts"}:
                self.assertEqual(body[key], value)
        self.assertEqual(body["facts"]["existing"], self.profile["facts"]["existing"])
        self.assertEqual(body["facts"]["coach_memory"]["entries"], [self.entry])

    def test_retry_deduplicates_and_rejects_changed_content(self):
        self.profile["facts"]["coach_memory"] = {"schema_version": 1, "entries": [self.entry]}
        self.mock_profile()
        self.assertTrue(self.client.remember(self.entry)["data"]["already_present"])
        self.client.request.assert_not_called()
        with self.assertRaises(ValueError):
            self.client.remember({**self.entry, "content": {"different": True}})
        self.client.request.assert_not_called()

    def test_conflict_stops_without_retry(self):
        self.mock_profile()
        self.client.request.side_effect = HTTPError("local", 409, "Conflict", {}, None)
        with self.assertRaises(HTTPError):
            self.client.remember(self.entry)
        self.assertEqual(self.client.request.call_count, 1)

    def test_wrong_mode_prevents_memory_write(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = io.StringIO(json.dumps({"mode": "demo", "data": self.profile}))
        self.client.opener = opener
        with self.assertRaises(ValueError):
            self.client.remember(self.entry)
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(opener.open.call_args.args[0].method, "GET")

    def test_rejects_nonlocal_targets_and_redirects(self):
        for url in ("https://example.com", "http://127.0.0.1@evil.test", "http://localhost/path"):
            with self.assertRaises(ValueError):
                helper.Client(url, "real")
        self.assertIsNone(helper.NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com"))

    def test_invalid_supersession_does_not_write(self):
        self.mock_profile()
        with self.assertRaises(ValueError):
            self.client.remember({**self.entry, "supersedes": "9297870c-45d7-4352-b4c2-72087b35f017"})
        self.client.request.assert_not_called()

    def test_agent_context_retains_workflow_and_date(self):
        self.client.request = Mock(return_value={"mode": "real", "data": {}})
        self.client.coaching_context("weekly", "2026-11-11")
        self.client.request.assert_called_once_with(
            "GET", "/coach/agent/context?workflow=weekly&as_of=2026-11-11")

    def test_apply_passes_model_authored_payload_unchanged_after_mode_check(self):
        self.mock_profile()
        proposal = {"workflow": "daily", "sessions": [], "evidence_hash": "current",
                    "expected_revision_id": "current-revision", "idempotency_key": "stable-key",
                    "rationale": "Retain the agreed session after reviewing reported function"}
        self.client.apply_proposal(proposal)
        self.client.verify_mode.assert_called_once_with()
        self.client.request.assert_called_once_with("POST", "/coach/agent/proposals", proposal)

    def test_wrong_mode_prevents_plan_write(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = io.StringIO(json.dumps({"mode": "demo", "data": {}}))
        self.client.opener = opener
        with self.assertRaises(ValueError):
            self.client.apply_proposal({"workflow": "weekly"})
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(opener.open.call_args.args[0].method, "GET")

    def test_plan_conflict_stops_without_changing_key_or_retrying(self):
        self.mock_profile()
        self.client.request.side_effect = HTTPError("local", 409, "Stale evidence", {}, None)
        proposal = {"idempotency_key": "original", "evidence_hash": "stale"}
        with self.assertRaises(HTTPError):
            self.client.apply_proposal(proposal)
        self.client.request.assert_called_once_with("POST", "/coach/agent/proposals", proposal)

    def test_revert_requires_valid_ids_and_a_reason_before_write(self):
        self.mock_profile()
        revision = "60a36d67-b0d8-4a57-87d5-4b697da7eedf"
        for args in (("bad", revision, "requested"), (revision, "bad", "requested"),
                     (revision, revision, "   ")):
            with self.assertRaises(ValueError):
                self.client.revert(*args)
        self.client.verify_mode.assert_not_called()
        self.client.request.assert_not_called()
        self.client.revert(revision, revision, "Athlete requested rollback")
        self.client.verify_mode.assert_called_once_with()
        self.client.request.assert_called_once_with("POST", f"/coach/agent/revisions/{revision}/rollback", {
            "expected_revision_id": revision, "reason": "Athlete requested rollback"})

    def test_cli_today_and_review_week_fetch_agent_context(self):
        for command, workflow in (("today", "daily"), ("review-week", "weekly")):
            with self.subTest(command=command), patch.object(helper, "Client", return_value=self.client), \
                    patch.object(sys, "argv", [str(HELPER), command]), patch("sys.stdout", new_callable=io.StringIO):
                self.client.coaching_context = Mock(return_value={"mode": "real", "data": {}})
                helper.main()
                self.client.coaching_context.assert_called_once_with(workflow, None)

    def test_cli_knowledge_selects_block_recipes_without_app_access(self):
        repo = HELPER.parents[3]
        args = [str(HELPER), "knowledge", "--repo", str(repo), "--workflow", "block",
                "--policies", "P019", "--recipes", "REC001", "--sources", "S072"]
        with patch.object(sys, "argv", args), patch.object(helper, "Client") as client, \
                patch("sys.stdout", new_callable=io.StringIO) as output:
            helper.main()
        client.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertTrue(result["integrity_ok"])
        self.assertEqual(result["package_version"], "1.1.0+privacy1")
        self.assertEqual([recipe["recipe_id"] for recipe in result["recipes"]], ["REC001"])
        self.assertEqual([policy["policy_id"] for policy in result["policies"]], ["P019"])
        self.assertIn("workflows/block_review.md", result["selected_files"])


if __name__ == "__main__":
    unittest.main()
