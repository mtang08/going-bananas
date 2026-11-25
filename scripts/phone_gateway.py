#!/usr/bin/env python3
"""Private Tailscale Serve entry point for the iPhone check-in."""
import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import partial
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PHONE_ASSETS = Path(__file__).resolve().parents[1] / "frontend/public/phone"
ASSET_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "phone.css": "text/css",
    "phone.js": "application/javascript",
    "sw.js": "application/javascript",
    "manifest.webmanifest": "application/manifest+json",
    "icon-192.png": "image/png",
    "icon-512.png": "image/png",
}
CHECKIN_PATH = re.compile(
    r"/api/v1/phone/checkins/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
MAX_BODY = 4096


@dataclass(frozen=True)
class PhoneAccess:
    host: str
    login: str
    mode: str
    api_port: int


class PhoneHandler(BaseHTTPRequestHandler):
    timeout = 15

    def __init__(self, *args, access, **kwargs):
        self.access = access
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        # Request URLs contain observation IDs. Keep access logs off.
        pass

    def reply(self, status, content=b"", media_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache" if self.command in {"HEAD", "GET"} else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)

    def authorized(self):
        if self.headers.get_all("Host") != [self.access.host]:
            self.reply(403, b"Phone hostname required.")
            return False
        if self.headers.get_all("Tailscale-User-Login") != [self.access.login]:
            self.reply(403, b"Connect with the owner's Tailscale account.")
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        filename = "index.html" if self.path == "/phone/" else self.path.removeprefix("/phone/")
        if not self.path.startswith("/phone/") or filename not in ASSET_TYPES:
            self.reply(404)
            return
        try:
            content = (PHONE_ASSETS / filename).read_bytes()
        except FileNotFoundError:
            self.reply(404)
            return
        self.reply(200, content, ASSET_TYPES[filename])

    do_HEAD = do_GET

    def do_PUT(self):
        if not self.authorized():
            return
        if not CHECKIN_PATH.fullmatch(self.path):
            self.reply(404)
            return
        if (self.headers.get_all("Origin") != [f"https://{self.access.host}"]
                or self.headers.get_all("X-Local-Request") != ["1"]):
            self.reply(403, b"Same-origin phone request required.")
            return
        if self.headers.get_content_type() != "application/json":
            self.reply(415)
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,5}", lengths[0]):
            self.reply(400)
            return
        length = int(lengths[0])
        if length > MAX_BODY:
            self.reply(413)
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self.reply(400)
            return
        # Build new headers after authorizing the request. Neither browser
        # credentials nor user-controlled forwarding headers reach the API.
        upstream = HTTPConnection("127.0.0.1", self.access.api_port, timeout=15)
        try:
            upstream.request("PUT", self.path, body, {
                "Content-Type": "application/json",
                "X-Local-Request": "1",
                "X-Phone-Mode": self.access.mode,
                "Origin": f"http://127.0.0.1:{self.access.api_port}",
            })
            response = upstream.getresponse()
            self.reply(response.status, response.read(), response.getheader("Content-Type", "application/json"))
        except (OSError, HTTPException):
            self.reply(503, b"The Mac API is unavailable.")
        finally:
            upstream.close()


def discover_access(demo):
    result = subprocess.run(["tailscale", "status", "--json"], capture_output=True, check=True, timeout=10)
    status = json.loads(result.stdout)
    if status.get("BackendState") != "Running":
        raise ValueError("Connect the Mac to Tailscale first.")
    device = status["Self"]
    hostname = device["DNSName"].rstrip(".").lower()
    login = status["User"][str(device["UserID"])]["LoginName"]
    if not hostname.endswith(".ts.net") or not login:
        raise ValueError("A tailnet DNS name and owner login are required.")
    return PhoneAccess(
        host=f"{hostname}:{8444 if demo else 8443}",
        login=login,
        mode="demo" if demo else "real",
        api_port=18000 if demo else 8000,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="use the dedicated demo origin and API")
    args = parser.parse_args()
    try:
        access = discover_access(args.demo)
        port = 8766 if args.demo else 8765
        with ThreadingHTTPServer(("127.0.0.1", port), partial(PhoneHandler, access=access)) as server:
            print(f"Phone gateway ({access.mode}): https://{access.host}/phone/", flush=True)
            print(f"Listening on 127.0.0.1:{port}. Press Ctrl+C to stop.", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as exc:
        sys.exit(f"Phone gateway could not start: {exc}")


if __name__ == "__main__":
    main()
