"""Slack Web API: post a templated message and read reactions; any failure leaves as the SLACK error class."""

from __future__ import annotations

from typing import Any

import httpx

from conversation_analyzer.errors import AnalyzerError
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ErrorClass


def _call(method: str, http: str, payload: dict[str, Any]) -> dict[str, Any]:
    env = get_settings().env
    url = f"{env.slack_api}/{method}"
    headers = {"Authorization": f"Bearer {env.slack_token}"}
    try:
        if http == "GET":
            resp = httpx.get(url, params=payload, headers=headers, timeout=30)
        else:
            resp = httpx.post(url, json=payload, headers=headers, timeout=30)
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AnalyzerError(ErrorClass.SLACK) from exc
    if not body.get("ok"):
        raise AnalyzerError(ErrorClass.SLACK)
    return body


def post(channel: str, text: str, thread_ts: str | None = None) -> tuple[str, str]:
    """Post a message; returns the channel ID and the message timestamp that identify it."""
    payload: dict[str, Any] = {"channel": channel, "text": text, "unfurl_links": False}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    body = _call("chat.postMessage", "POST", payload)
    return body["channel"], body["ts"]


def reactions(channel: str, ts: str) -> dict[str, list[str]]:
    """Reaction name to the IDs of the users who added it."""
    body = _call("reactions.get", "GET", {"channel": channel, "timestamp": ts, "full": "true"})
    found = (body.get("message") or {}).get("reactions") or []
    return {r["name"]: list(r.get("users") or []) for r in found}
