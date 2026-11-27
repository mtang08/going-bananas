"""Check the native proposal list seeded with tests/fixtures/proposal-list.sql."""

import json
from http.client import HTTPConnection

PATH = "/api/v1/coach/proposals"


def read_response(port, query, path=PATH):
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path + query)
        response = connection.getresponse()
        body = json.loads(response.read())
        if response.getheader("Content-Type", "").split(";")[0] != "application/json":
            raise ValueError("expected JSON")
        request_id = response.getheader("X-Request-ID")
        if not request_id or response.getheader("Cache-Control") != "no-store":
            raise ValueError("missing request ID or cache policy")
        if response.status == 200:
            if body["mode"] != "test" or body["data_revision"] != 17:
                raise ValueError("load the proposal fixture in test mode")
        elif response.status == 422:
            if body["error"]["request_id"] != request_id:
                raise ValueError("validation error has a different request ID")
            body["error"]["request_id"] = "<request-id>"
        else:
            raise ValueError(f"unexpected HTTP {response.status}")
        return response.status, body
    finally:
        connection.close()


def check_list(port):
    cases = {
        "": 50,
        "?status=open": 1,
        "?status=pending": 1,
        "?status=accepted": 48,
        "?status=partially_accepted": 1,
        "?status=rejected": 1,
        "?status=stale": 0,
        "?status=invalid": 0,
        "?status=discarded": 1,
        "?status=": None,
        "?status=bogus": None,
        "?status=pending&status=accepted": 48,
        "?status=bogus&status=pending": 1,
        "?status=pending&status=bogus": None,
    }
    for query, expected_count in cases.items():
        status, body = read_response(port, query)
        if expected_count is None:
            valid = (
                status == 422 and body["error"]["fields"][0]["field"] == "query.status"
            )
        else:
            valid = status == 200 and len(body["data"]["items"]) == expected_count
        if not valid:
            raise SystemExit(f"Unexpected native response on GET {PATH}{query}")
        print(f"PASS {status} GET {PATH}{query}")
