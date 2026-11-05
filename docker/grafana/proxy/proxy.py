"""TLS front for the emulator: fake OAuth tokens, and a cache of repeated dashboard queries (local only)."""

import contextlib
import hashlib
import http.client
import json
import os
import re
import ssl
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EMULATOR = ("bigquery", 9050)
TTL = float(os.environ.get("CACHE_TTL_SECONDS", "600"))
TOKEN = json.dumps({"access_token": "local", "token_type": "Bearer", "expires_in": 3600}).encode()
# $__timeFilter resolves to the current millisecond: matching on the hour lets an unchanged reload hit the cache.
TIMESTAMP = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}):\d{2}:\d{2}(\.\d+)?Z?")

cache: dict[str, tuple[float, int, bytes]] = {}
lock = threading.Lock()


def query_key(body: bytes) -> str | None:
    """A query job's identity without its random job ID and labels, and with timestamps cut to the hour."""
    try:
        job = json.loads(body)
    except ValueError:
        return None
    job.pop("jobReference", None)
    job.get("configuration", {}).pop("labels", None)  # Grafana labels browser jobs with the panel that sent them
    if "query" not in job.get("configuration", {}):
        return None
    text = TIMESTAMP.sub(r"\1", json.dumps(job, sort_keys=True))
    return "POST " + hashlib.sha256(text.encode()).hexdigest()


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:
        pass

    def reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):  # the browser cancelled the panel's query
            self.wfile.write(body)

    def forward(self, method: str, body: bytes | None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection(*EMULATOR, timeout=600)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        conn.request(method, self.path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()

    def cached(self, key: str | None, method: str, body: bytes | None, done) -> None:
        now = time.monotonic()
        with lock:
            hit = cache.get(key) if key else None
        if hit and now - hit[0] < TTL:
            print(f"hit  {method} {self.path.split('?')[0][-40:]}")
            return self.reply(hit[1], hit[2])
        status, data = self.forward(method, body)
        if key and status == 200 and done(data):
            with lock:
                cache[key] = (now, status, data)
        self.reply(status, data)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.headers.get("Host", "").startswith(("oauth2.", "www.")):
            return self.reply(200, TOKEN)
        key = query_key(body) if re.search(r"/projects/[^/]+/jobs$", self.path.split("?")[0]) else None
        self.cached(key, "POST", body, lambda data: True)

    def do_GET(self) -> None:
        # A finished job's status and results never change, so a cached POST's follow-up calls are cached too.
        def done(data: bytes) -> bool:
            d = json.loads(data)
            return d.get("jobComplete") is True or d.get("status", {}).get("state") == "DONE"

        self.cached("GET " + self.path, "GET", None, done)


def certificate() -> None:
    if not os.path.exists("/certs/ca.pem"):
        names = "DNS:bigquery.googleapis.com,DNS:oauth2.googleapis.com,DNS:www.googleapis.com"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "3650",
                "-subj",
                "/CN=local-gcp-proxy",
                "-addext",
                f"subjectAltName={names}",
                "-keyout",
                "/certs/key.pem",
                "-out",
                "/certs/ca.pem",
            ],
            check=True,
            capture_output=True,
        )
        for f in ("key.pem", "ca.pem"):
            os.chmod(f"/certs/{f}", 0o644)


if __name__ == "__main__":
    certificate()
    server = ThreadingHTTPServer(("", 443), Proxy)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain("/certs/ca.pem", "/certs/key.pem")
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
