"""Loopback access for Codex coaching, validated plans, check-ins, and memory."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, base_url: str, mode: str):
        url = urlsplit(base_url)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost"}
                or url.username or url.password or url.path not in {"", "/"}
                or url.query or url.fragment):
            raise ValueError("Use a loopback HTTP origin without credentials or a path")
        self.base = base_url.rstrip("/")
        self.mode = mode
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method: str, path: str, body=None):
        request = Request(self.base + "/api/v1" + path, method=method,
                          data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "X-Local-Request": "1"})
        with self.opener.open(request, timeout=20) as response:
            result = json.load(response)
        if result.get("mode") != self.mode:
            raise ValueError("App mode mismatch; do not use this response as athlete history")
        return result

    def verify_mode(self):
        return self.request("GET", "/profile")

    def coaching_context(self, workflow: str, as_of: str | None = None):
        query = {"workflow": workflow}
        if as_of:
            query["as_of"] = as_of
        return self.request("GET", "/coach/agent/context?" + urlencode(query))

    def apply_proposal(self, proposal: dict):
        # Server owns dose/schedule/conflict validation and atomic persistence.
        # Checking the mode first prevents writing to an unintended database.
        self.verify_mode()
        return self.request("POST", "/coach/agent/proposals", proposal)

    def revert(self, revision_id: str, expected_revision_id: str, reason: str):
        UUID(revision_id)
        UUID(expected_revision_id)
        if not reason.strip():
            raise ValueError("A rollback reason is required")
        self.verify_mode()
        return self.request("POST", f"/coach/agent/revisions/{revision_id}/rollback", {
            "expected_revision_id": expected_revision_id, "reason": reason,
        })

    def remember(self, entry: dict):
        validate_entry(entry)
        response = self.verify_mode()
        profile = copy.deepcopy(response["data"])
        facts = profile.setdefault("facts", {})
        memory = facts.setdefault("coach_memory", {"schema_version": 1, "entries": []})
        if not isinstance(memory, dict) or memory.get("schema_version") != 1 or not isinstance(memory.get("entries"), list):
            raise ValueError("Unsupported coaching memory format; inspect before writing")
        entries = memory["entries"]
        for old in entries:
            if old["id"] == entry["id"]:
                if old != entry:
                    raise ValueError("Memory ID already exists with different content")
                return {"mode": self.mode, "data": {"saved": True, "already_present": True, "id": entry["id"]}}
        if entry.get("supersedes") and not any(old["id"] == entry["supersedes"] for old in entries):
            raise ValueError("Superseded entry does not exist")
        entries.append(entry)
        profile["expected_version"] = profile.pop("version")
        return self.request("PUT", "/profile", profile)


def validate_entry(entry):
    if not isinstance(entry, dict):
        raise TypeError("Memory entry must be an object")
    if set(entry) - {"id", "kind", "recorded_at", "content", "supersedes"}:
        raise ValueError("Unexpected memory fields")
    UUID(entry["id"])
    if entry["kind"] not in {"athlete_fact", "goal", "preference", "review", "follow_up"}:
        raise ValueError("Invalid memory kind")
    stamp = datetime.fromisoformat(entry["recorded_at"])
    if stamp.utcoffset() is None:
        raise ValueError("Memory timestamp requires UTC offset")
    if not isinstance(entry["content"], dict) or not entry["content"]:
        raise ValueError("Memory content must be a nonempty object")
    if entry.get("supersedes"):
        UUID(entry["supersedes"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mode", choices=["real", "demo", "test"], default="real")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("profile", "status", "sync"):
        sub.add_parser(command)
    for command in ("today", "review-week"):
        sub.add_parser(command).add_argument("--as-of", help="ISO date; omit for the app's local date")
    sub.add_parser("schema")
    sub.add_parser("inspect")
    revert = sub.add_parser("revert")
    revert.add_argument("--revision", required=True, help="Revision to undo")
    revert.add_argument("--expected-revision", required=True, help="Current revision ID from fresh context")
    revert.add_argument("--reason", required=True)
    context = sub.add_parser("context")
    context.add_argument("--workflow", choices=["daily", "weekly"], default="daily")
    context.add_argument("--as-of", help="ISO date; omit to use the app timezone's current date")
    for command in ("checkin", "remember", "apply", "link-completion"):
        sub.add_parser(command).add_argument("--file", required=True, type=Path)
    kb = sub.add_parser("knowledge")
    kb.add_argument("--repo", type=Path, required=True)
    kb.add_argument("--workflow", choices=["daily", "weekly", "block"], required=True)
    for option in ("topics", "policies", "sources", "recipes"):
        kb.add_argument("--" + option, nargs="*", default=[])
    args = parser.parse_args()
    if args.command == "knowledge":
        sys.path.insert(0, str(args.repo.resolve() / "backend"))
        from app.services.knowledge import load_knowledge
        result = asdict(load_knowledge(args.workflow, args.topics, args.policies, args.sources,
                                      recipe_ids=args.recipes,
                                      root=args.repo.resolve() / "running_coach_kb"))
    else:
        client = Client(args.base_url, args.mode)
        if args.command == "remember":
            result = client.remember(json.loads(args.file.read_text()))
        elif args.command == "profile":
            result = client.verify_mode()
        elif args.command in {"today", "review-week", "context"}:
            workflow = {"today": "daily", "review-week": "weekly"}.get(args.command)
            result = client.coaching_context(workflow or args.workflow, args.as_of)
        elif args.command == "schema":
            result = client.request("GET", "/coach/agent/schema")
        elif args.command == "inspect":
            result = client.request("GET", "/coach/agent/revisions")
        elif args.command == "apply":
            result = client.apply_proposal(json.loads(args.file.read_text()))
        elif args.command == "revert":
            result = client.revert(args.revision, args.expected_revision, args.reason)
        elif args.command == "status":
            result = client.request("GET", "/sync/status")
        else:
            client.verify_mode()  # Refuse wrong-mode writes before sending them.
            if args.command == "sync":
                status = client.request("GET", "/sync/status")
                result = status if status["data"]["active_jobs"] else client.request("POST", "/sync", {})
            else:
                path = "/completion-links" if args.command == "link-completion" else "/checkins"
                result = client.request("POST", path, json.loads(args.file.read_text()))
    print(json.dumps(result, default=str, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except HTTPError as exc:
        print(f"App HTTP {exc.code}: {exc.read().decode()[:2000]}", file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, TypeError, OSError, URLError) as exc:
        print(f"Coach access failed: {exc}", file=sys.stderr)
        sys.exit(1)
