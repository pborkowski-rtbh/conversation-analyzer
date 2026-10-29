"""Local stand-ins for Slack, GitHub and Cloud Run executions; tests steer them through /_test/* endpoints."""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

LOCK = threading.RLock()  # reset() takes it again inside a request
STATE: dict = {}


def reset() -> None:
    with LOCK:
        STATE.clear()
        STATE.update({"messages": [], "reactions": {}, "commits": {}, "executions": {}, "seq": 0})


reset()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep the container quiet
        pass

    def _send(self, code: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        if "application/x-www-form-urlencoded" in (self.headers.get("Content-Type") or ""):
            return {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        return json.loads(raw)

    def do_GET(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def _route(self, method: str) -> None:
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        body = self._body() if method == "POST" else {}
        path = url.path
        with LOCK:
            if path == "/_test/reset":
                reset()
                return self._send(200, {"ok": True})
            if path == "/_test/state":
                return self._send(200, STATE)
            if path == "/_test/slack/reaction":
                key = f"{body['channel']}|{body['ts']}"
                STATE["reactions"].setdefault(key, []).append({"name": body["name"], "user": body["user"]})
                return self._send(200, {"ok": True})
            if path == "/_test/github/commits":
                STATE["commits"].setdefault(body["repository"], []).extend(body["commits"])
                return self._send(200, {"ok": True})
            if path == "/_test/cloudrun/executions":
                STATE["executions"].setdefault(body["job"], []).extend(body["executions"])
                return self._send(200, {"ok": True})
            if path == "/slack/api/chat.postMessage":
                STATE["seq"] += 1
                ts = f"{int(time.time())}.{STATE['seq']:06d}"
                STATE["messages"].append({**body, "ts": ts})
                return self._send(200, {"ok": True, "channel": body.get("channel"), "ts": ts})
            if path == "/slack/api/reactions.get":
                params = {**q, **body}
                key = f"{params.get('channel')}|{params.get('timestamp')}"
                grouped: dict[str, list[str]] = {}
                for r in STATE["reactions"].get(key, []):
                    grouped.setdefault(r["name"], []).append(r["user"])
                reactions = [{"name": n, "users": u, "count": len(u)} for n, u in grouped.items()]
                return self._send(200, {"ok": True, "type": "message", "message": {"reactions": reactions}})
            m = re.match(r"^/github/repos/([^/]+/[^/]+)/commits$", path)
            if m:
                since = q.get("since", "")
                commits = [c for c in STATE["commits"].get(m[1], []) if c["commit"]["committer"]["date"] >= since]
                return self._send(200, commits)
            m = re.match(r"^/cloudrun/v2/projects/[^/]+/locations/[^/]+/jobs$", path)
            if m:
                return self._send(200, {"jobs": [{"name": f"x/jobs/{j}"} for j in STATE["executions"]]})
            m = re.match(r"^/cloudrun/v2/projects/[^/]+/locations/[^/]+/jobs/([^/]+)/executions$", path)
            if m:
                return self._send(200, {"executions": STATE["executions"].get(m[1], [])})
        self._send(404, {"ok": False, "error": "not_found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8088), Handler).serve_forever()
