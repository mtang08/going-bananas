"""Exercise the private gateway against a loopback receipt server with synthetic data."""
import json
from contextlib import contextmanager
from functools import partial
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import unittest

from phone_gateway import PhoneAccess, PhoneHandler


@contextmanager
def serving(handler):
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


class ReceiptHandler(BaseHTTPRequestHandler):
    def do_PUT(self):
        self.server.writes.append((self.path, self.headers, self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data":{"saved":true}}')

    def log_message(self, format, *args):
        pass


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.api = serving(ReceiptHandler)
        self.backend = self.api.__enter__()
        self.addCleanup(self.api.__exit__, None, None, None)
        self.backend.writes = []
        self.access = PhoneAccess("mac.example.ts.net:8444", "owner@example.test", "demo", self.backend.server_port)
        self.gateway = serving(partial(PhoneHandler, access=self.access))
        self.server = self.gateway.__enter__()
        self.addCleanup(self.gateway.__exit__, None, None, None)
        self.headers = {"Host": self.access.host, "Tailscale-User-Login": self.access.login}
        self.path = "/api/v1/phone/checkins/a0000000-0000-4000-8000-000000000001"
        self.write_headers = {
            **self.headers, "Origin": f"https://{self.access.host}", "Content-Type": "application/json",
            "X-Local-Request": "1",
        }

    def request(self, method, path, headers, body=None):
        connection = HTTPConnection(*self.server.server_address, timeout=2)
        try:
            connection.request(method, path, body, headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_owner_on_private_origin_can_read_phone_shell_only(self):
        status, body = self.request("GET", "/phone/", self.headers)
        self.assertEqual(status, 200)
        self.assertIn(b"manifest", body)
        for path in ("/phone/?from=safari", "/phone/index.html?launch=1"):
            self.assertEqual(self.request("GET", path, self.headers), (status, body))
        for path in ("/", "/phone", "/?from=safari"):
            with self.subTest(path=path):
                conn = HTTPConnection(*self.server.server_address, timeout=2)
                try:
                    conn.request("GET", path, headers=self.headers)
                    response = conn.getresponse()
                    self.assertEqual((response.status, response.getheader("Location")), (302, "/phone/"))
                finally:
                    conn.close()
        for path in ("/api/v1/profile", "/phone/../.env", "/phone/%2e%2e/index.html"):
            with self.subTest(path=path):
                self.assertEqual(self.request("GET", path, self.headers)[0], 404)
        for headers in ({"Host": self.access.host}, {**self.headers, "Host": "localhost"},
                        {**self.headers, "Tailscale-User-Login": "other@example.test"}):
            self.assertEqual(self.request("GET", "/phone/", headers)[0], 403)

    def test_only_same_origin_scoped_json_writes_reach_api(self):
        for patch in ({"Origin": "https://other.example"}, {"X-Local-Request": ""}, {"Origin": ""}):
            status, _ = self.request("PUT", self.path, {**self.write_headers, **patch}, b"{}")
            self.assertEqual(status, 403)
        status, _ = self.request("PUT", "/api/v1/profile", self.write_headers, b"{}")
        self.assertEqual(status, 404)
        self.assertEqual(self.backend.writes, [])

        body = b'{"pain":0,"walking_response":null,"observed_at":"2026-01-01T08:00:00Z"}'
        headers = {**self.write_headers, "Cookie": "test=x", "X-Phone-Mode": "real"}
        status, receipt = self.request("PUT", self.path, headers, body)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(receipt)["data"]["saved"])
        [(path, forwarded, forwarded_body)] = self.backend.writes
        self.assertEqual((path, forwarded_body), (self.path, body))
        self.assertEqual(forwarded.get("Origin"), f"http://127.0.0.1:{self.backend.server_port}")
        self.assertEqual(forwarded.get("Host"), f"127.0.0.1:{self.backend.server_port}")
        self.assertEqual(forwarded.get("X-Local-Request"), "1")
        self.assertEqual(forwarded.get("X-Phone-Mode"), "demo")
        self.assertNotIn("Cookie", forwarded)
        self.assertNotIn("Tailscale-User-Login", forwarded)


if __name__ == "__main__":
    unittest.main()
