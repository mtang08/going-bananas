"""Run python3 scripts/test-db.py phone-checkins for synthetic native gateway, HTTP and PostgreSQL regressions."""

import json
import re
import selectors
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from http.client import HTTPConnection
from pathlib import Path

import psycopg
from check_gcal_replay import connect, test_url
from test_proposal_slice import (
    MODULE,
    ROOT,
    listener,
    migrated_schema,
)

HOST = "synthetic.ts.net:8444"
OWNER = "athlete@example.invalid"
ENTRY = "1258ffe0-a19e-4770-8f40-6d2742e2e120"
PREFIX = "/api/v1"
PHONE = PREFIX + "/phone/checkins/" + ENTRY
CHECKINS = PREFIX + "/v2/checkins"
BODY = {"observed_at": "2025-02-15T23:30:00-05:00", "pain": 0, "walking_response": None}


@contextmanager
def server(env, binary):
    with listener(
        [binary, "-test.run=^TestCheckinFixtureServer$", "-test.timeout=3m"],
        env=dict(
            env,
            CHECKIN_HTTP_FIXTURE="1",
            PHONE_FIXTURE_ASSETS=str(ROOT / "frontend/public/phone"),
        ),
        stdout=subprocess.PIPE,
        text=True,
    ) as candidate:
        with selectors.DefaultSelector() as sel:
            sel.register(candidate.stdout, selectors.EVENT_READ)
            assert sel.select(timeout=20), "check-in fixture listener did not start"
        line = candidate.stdout.readline().strip()
        assert re.fullmatch(r"\d+ \d+", line), line
        yield tuple(map(int, line.split()))


def setup(env):
    with connect(env) as db:
        db.execute("""CREATE TABLE fixture_hooks(seq bigint GENERATED ALWAYS AS IDENTITY,kind text NOT NULL,scopes text[]);
                      CREATE TABLE fixture_abort(kind text PRIMARY KEY);
                      CREATE FUNCTION fixture_fail() RETURNS trigger LANGUAGE plpgsql AS $$
                        BEGIN IF EXISTS(SELECT 1 FROM fixture_abort WHERE kind=NEW.kind) THEN RAISE EXCEPTION 'test failure'; END IF;
                        RETURN NEW; END $$;
                      CREATE TRIGGER fixture_fail BEFORE INSERT ON fixture_hooks FOR EACH ROW EXECUTE FUNCTION fixture_fail()""")
        # An old receipt predates pain_reported in saved revision payloads.
        fixed = "c8c05271-27d7-41b7-9220-ed59f2140db6"
        db.execute(
            """INSERT INTO checkins_v2(id,idempotency_key,version,kind,observed_at,recorded_at,context_tags,note,schema_version)
            VALUES (%s,'older',2,'exception','2025-02-12T14:00Z','2025-02-12T15:00Z','{}','latest',2)""",
            (fixed,),
        )
        db.execute(
            """INSERT INTO checkin_v2_revisions(id,checkin_id,version,payload,recorded_at)
             SELECT gen_random_uuid(),id,1,(to_jsonb(c)-'pain_reported') || '{"version":1,"note":"original","symptoms":[]}',
                   recorded_at FROM checkins_v2 c WHERE id=%s""",
            (fixed,),
        )


def names(env):
    with connect(env) as db:
        checkins = dict(
            db.execute("SELECT id::text,idempotency_key FROM checkins_v2").fetchall()
        )
        symptoms = {}
        for (uid,) in db.execute("SELECT id::text FROM symptom_reports"):
            for cid, key in checkins.items():
                if uid[4:] == cid[4:]:
                    symptoms[uid] = key + ":symptom:" + uid[:4]
        return checkins, symptoms


def snapshot(env):
    ids, _ = names(env)
    with connect(env) as db:
        hooks = []
        for kind, scopes in db.execute(
            "SELECT kind,scopes FROM fixture_hooks ORDER BY seq"
        ):
            hooks.append(
                (
                    kind,
                    sorted(
                        "checkin:" + ids[v[8:]] if v.startswith("checkin:") else v
                        for v in scopes or []
                    ),
                )
            )
        return hooks, db.execute(
            "SELECT data_revision FROM app_state WHERE id=1"
        ).fetchone()[0]


def canonical(obj, env):
    ids, symptoms = names(env)
    with connect(env) as db:
        ids.update(
            db.execute(
                "SELECT id::text,'finding:'||rule_code||':'||entity_key FROM exception_findings"
            ).fetchall()
        )

    def visit(data):
        if isinstance(data, list):
            return [visit(x) for x in data]
        if isinstance(data, dict):
            out = {}
            for k, x in data.items():
                if k == "id" and "site" in data:
                    # Deleted symptom IDs in historical receipts still encode original insertion order.
                    out[k] = int(x[:4], 16)
                elif k == "recorded_at":
                    assert datetime.fromisoformat(x).tzinfo
                    out[k] = "recorded"
                elif k == "observed_at":
                    out[k] = datetime.fromisoformat(x).astimezone(UTC).isoformat()
                elif k == "request_id":
                    assert x
                    out[k] = "request"
                else:
                    out[k] = visit(x)
            return out
        return (
            ids.get(data, symptoms.get(data, data)) if isinstance(data, str) else data
        )

    return visit(obj)


def request(port, method, path, body, headers):
    client = HTTPConnection("127.0.0.1", port, timeout=8)
    try:
        payload = json.dumps(body).encode() if body is not None else None
        client.request(method, path, payload, headers)
        response = client.getresponse()
        raw = response.read()
        return response.status, response.headers, raw
    finally:
        client.close()


def exercise(binary, env):
    setup(env)
    with server(env, binary) as (api, phone):

        def call(method, path, body=None, *, gateway=False, headers=None, status=200):
            defaults = {"X-Local-Request": "1", "Content-Type": "application/json"}
            if gateway:
                defaults.update(
                    Host=HOST,
                    Origin="https://" + HOST,
                    **{"Tailscale-User-Login": OWNER},
                )
            if headers:
                defaults.update(headers)
            for uid, name in names(env)[0].items():
                path = path.replace("{" + name + "}", uid)
            before = snapshot(env)
            code, head, raw = request(
                phone if gateway else api, method, path, body, defaults
            )
            assert code == status, (method, path, status, code, raw)
            if status < 500 and (status >= 400 or method in ("GET", "HEAD")):
                assert snapshot(env) == before
            if head.get_content_type() == "application/json" and raw:
                reply = canonical(json.loads(raw), env)
                if "data_revision" in reply:
                    assert reply["mode"] == "test"
                    assert reply["data_revision"] == snapshot(env)[1]
                return reply
            if status == 302:
                assert head["Location"] == "/phone/"
            return raw

        for verb, path, status in [
            ("GET", "/", 302),
            ("GET", "/phone/", 200),
            ("HEAD", "/phone/phone.js", 200),
            ("GET", "/phone/manifest.webmanifest?v=1", 200),
            ("GET", "/other", 404),
        ]:
            call(verb, path, gateway=True, status=status)
        for overrides in [
            {"Host": "localhost"},
            {"Tailscale-User-Login": "different"},
            {"Origin": ""},
            {"X-Local-Request": "0"},
        ]:
            call("PUT", PHONE, BODY, gateway=True, headers=overrides, status=403)
        call("PUT", PHONE + "?x=y", BODY, gateway=True, status=404)
        call(
            "PUT",
            PHONE,
            BODY,
            gateway=True,
            headers={"Content-Type": "text/plain"},
            status=415,
        )
        call("PUT", PHONE, "x" * 4096, gateway=True, status=413)
        call("PUT", PHONE, BODY, headers={"X-Phone-Mode": "demo"}, status=409)
        for edits in [
            {"pain": True},
            {"pain": 2},
            {"pain": 10, "walking_response": "other"},
            {"unknown": True},
            {"observed_at": "2025-02-15T10:00:00"},
        ]:
            call("PUT", PHONE, dict(BODY, **edits), gateway=True, status=422)
        before = snapshot(env)
        saved = call("PUT", PHONE, BODY, gateway=True)
        after = snapshot(env)
        assert after[1] == before[1] + 1
        assert [kind for kind, _ in after[0][len(before[0]) :]] == ["detect", "refresh"]
        assert saved["data"] == {"id": ENTRY}
        assert call("PUT", PHONE, BODY, gateway=True) == saved
        assert snapshot(env) == after
        call(
            "PUT",
            PHONE,
            dict(BODY, pain=2, walking_response="eased"),
            gateway=True,
            status=409,
        )
        call(
            "PUT",
            PHONE.replace(ENTRY, ENTRY[:-1] + "1"),
            dict(
                BODY,
                pain=2,
                walking_response="eased",
                observed_at="2025-02-15T22:30:00-05:00",
            ),
            gateway=True,
        )
        assert (
            len(
                call("GET", CHECKINS + "?start=2025-02-15&end=2025-02-15")["data"][
                    "items"
                ]
            )
            == 2
        )
        generic = {
            "idempotency_key": "record",
            "kind": "exception",
            "observed_at": "2025-02-16T10:00:00-05:00",
            "symptoms": [
                {
                    "site": " ankle ",
                    "side": "left",
                    "severity": "2.1",
                    "timing": "during",
                }
            ],
        }
        created = call("POST", CHECKINS, generic, status=201)
        assert (
            created["data"]["version"] == 1
            and created["data"]["symptoms"][0]["site"] == "ankle"
        )
        call(
            "PATCH",
            CHECKINS + "/{record}",
            {"expected_version": 1, "note": "new", "symptoms": []},
        )
        replay = call("POST", CHECKINS, generic)
        assert replay["data"] == created["data"]
        call("POST", CHECKINS, dict(generic, note="different"), status=409)
        call(
            "PATCH",
            CHECKINS + "/{record}",
            {"expected_version": 1, "fatigue": 2},
            status=409,
        )
        call(
            "POST",
            CHECKINS,
            dict(generic, idempotency_key="phone-first-steps:reserved"),
            status=422,
        )
        call(
            "POST",
            CHECKINS,
            dict(generic, idempotency_key="follow", kind="post_run"),
            status=422,
        )
        call(
            "POST",
            CHECKINS,
            dict(generic, idempotency_key="bad", pain_reported=False),
            status=422,
        )
        call("POST", CHECKINS, dict(generic, fatigue=99), status=422)
        old = call(
            "POST",
            CHECKINS,
            {
                "idempotency_key": "older",
                "kind": "exception",
                "observed_at": "2025-02-12T14:00:00Z",
                "note": "original",
            },
        )
        assert old["data"]["version"] == 1 and old["data"]["pain_reported"] is None
        with connect(env) as db:
            db.execute("INSERT INTO fixture_abort VALUES ('refresh')")
        call(
            "POST",
            CHECKINS,
            dict(
                generic,
                idempotency_key="rollback",
                observed_at="2025-02-16T11:00:00-05:00",
            ),
            status=500,
        )
        with connect(env) as db:
            assert db.execute(
                "SELECT count(*) FROM checkins_v2 WHERE idempotency_key='rollback'"
            ).fetchone() == (0,)
            db.execute("DELETE FROM fixture_abort")
        call(
            "POST",
            CHECKINS,
            dict(
                generic,
                idempotency_key="rollback",
                observed_at="2025-02-16T11:00:00-05:00",
            ),
            status=201,
        )
        # Phone detection is part of the source transaction. Generic submissions commit the receipt before detection.
        other = PHONE.replace(ENTRY, ENTRY[:-1] + "2")
        late = dict(BODY, observed_at="2025-02-17T10:00:00Z")
        split = dict(
            generic, idempotency_key="split", observed_at="2025-02-17T11:00:00Z"
        )
        with connect(env) as db:
            db.execute("INSERT INTO fixture_abort VALUES ('detect')")
        call("PUT", other, late, gateway=True, status=500)
        call("POST", CHECKINS, split, status=500)
        with connect(env) as db:
            assert db.execute(
                "SELECT count(*) FROM checkins_v2 WHERE idempotency_key = %s",
                ("phone-first-steps:" + other.rsplit("/", 1)[1],),
            ).fetchone() == (0,)
            assert db.execute(
                "SELECT count(*) FROM checkins_v2 WHERE idempotency_key='split'"
            ).fetchone() == (1,)
            db.execute("DELETE FROM fixture_abort")
        call("POST", CHECKINS, split)
        headers = {
            "Host": HOST,
            "Tailscale-User-Login": OWNER,
            "Origin": "https://" + HOST,
            "X-Local-Request": "1",
            "Content-Type": "application/json",
        }
        before = snapshot(env)[1]
        with ThreadPoolExecutor(max_workers=2) as workers:
            replies = list(
                workers.map(
                    lambda _, port=phone: request(port, "PUT", other, late, headers),
                    range(2),
                )
            )
        assert (
            all(code == 200 for code, _, _ in replies)
            and replies[0][2] == replies[1][2]
        )
        assert snapshot(env)[1] == before + 1
        alternate = dict(
            generic, idempotency_key="alternate", observed_at="2025-02-19T12:00+0530"
        )
        created_alternate = call("POST", CHECKINS, alternate, status=201)
        assert created_alternate["data"]["observed_at"] == "2025-02-19T06:30:00+00:00"
        call(
            "PATCH",
            CHECKINS + "/{alternate}",
            {"expected_version": "1.0", "fatigue": "1.1"},
        )
        call(
            "PATCH",
            CHECKINS + "/{alternate}",
            {"expected_version": "invalid"},
            status=422,
        )
        live = dict(
            generic,
            idempotency_key="illness",
            observed_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            illness="present",
            symptoms=[],
        )
        result = call("POST", CHECKINS, live, status=201)["data"]["exceptions"]
        assert result["new_finding_ids"] and result["review_recommended"]
        assert (
            call("POST", CHECKINS, live)["data"]["exceptions"]["new_finding_ids"] == []
        )
        call("GET", CHECKINS)
    print(
        "PASS synthetic phone gateway, modes and request guards, check-in HTTP writes, receipts, history, refresh rollback and civil-date reads"
    )


def positive_refresh(binary, env):
    fixed = "2026-11-15T15:00:00Z"
    headers = {"X-Local-Request": "1", "Content-Type": "application/json"}

    def state(env):
        with connect(env) as db:
            rows = db.execute("""SELECT metric_id,subject_type,subject_key,method_version,status,value
                FROM metric_results WHERE is_current ORDER BY metric_id,subject_type,subject_key,method_version""").fetchall()
            prompts = db.execute(
                """SELECT id::text,kind,status FROM prompts ORDER BY kind,id"""
            ).fetchall()
            revision = db.execute(
                "SELECT data_revision FROM app_state WHERE id=1"
            ).fetchone()[0]
            return rows, prompts, revision

    env["CHECKIN_REFRESH_CLOCK"] = fixed
    with connect(env) as db:
        db.execute("""INSERT INTO prompts(id,kind,opens_at,closes_at,status)
              VALUES ('bd66b144-0194-4690-aad1-b7e15835ca62','missing_activity',
                    '2026-11-10T10:00Z','2026-11-12T10:00Z','open')""")
    with server(env, binary) as (api, _):

        def submit():
            code, _, raw = request(
                api,
                "PUT",
                PHONE,
                dict(BODY, observed_at="2026-11-15T09:00:00-05:00"),
                headers,
            )
            assert code == 200, (code, raw)
            return json.loads(raw)

        receipt = submit()
        previous = state(env)
        rows, prompts, revision = previous
        assert len(rows) == 37
        assert prompts[0][2] == "expired"
        assert revision == receipt["data_revision"]
        assert submit() == receipt and state(env) == previous
    print(
        f"PASS full check-in refresh: {len(previous[0])} current metric results, prompt expiry and duplicate receipt"
    )


def main():
    url = test_url()
    with (
        psycopg.connect(
            url.set(drivername="postgresql").render_as_string(hide_password=False),
            autocommit=True,
        ) as db,
        tempfile.TemporaryDirectory(dir=ROOT / "private") as tmp,
    ):
        directory = Path(tmp)
        binary = directory / "phone-checkins.test"
        subprocess.run(
            ["go", "test", "-race", "-c", "-o", binary, "./internal/checkinhttp"],
            cwd=MODULE,
            check=True,
        )
        with migrated_schema(db, url, directory / "phone", "5173") as env:
            exercise(binary, env)
            subprocess.run(
                [
                    "go",
                    "test",
                    "-race",
                    "-count=1",
                    "-run",
                    "^TestFindingLifecycle$",
                    "./internal/exceptions",
                ],
                cwd=MODULE,
                env=dict(env, CHECKIN_HTTP_FIXTURE="1"),
                check=True,
            )
        with migrated_schema(db, url, directory / "refresh", "5173") as env:
            positive_refresh(binary, env)


if __name__ == "__main__":
    main()
