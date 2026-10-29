"""Language-model calls on EU endpoints only, at temperature 0, with structured output (§3.1, §6.3, §12.12)."""

from __future__ import annotations

import json
import random
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ValidationError

from conversation_analyzer.errors import AnalyzerError, JudgeApiError, JudgeOutputError, TokenLimitError
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ErrorClass


@dataclass
class Usage:
    """Tokens per model and throttled calls of one run; the run record stores them (§12.12)."""

    input_tokens: Counter[str] = field(default_factory=Counter)
    output_tokens: Counter[str] = field(default_factory=Counter)
    throttled: int = 0
    tokens_before_today: int = 0  # tokens already used today by earlier runs
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, inp: int, out: int) -> None:
        with self.lock:
            self.input_tokens[model] += inp
            self.output_tokens[model] += out

    def total(self) -> int:
        return sum(self.input_tokens.values()) + sum(self.output_tokens.values())

    def rows(self) -> list[dict[str, Any]]:
        models = sorted(set(self.input_tokens) | set(self.output_tokens))
        return [
            {"model": m, "input_tokens": self.input_tokens[m], "output_tokens": self.output_tokens[m]} for m in models
        ]


class Judge(Protocol):
    def generate(self, model: str, system: str, prompt: str, form: type[BaseModel], usage: Usage) -> BaseModel: ...


def api_host(location: str) -> str:
    if location in ("eu", "us"):
        return f"aiplatform.{location}.rep.googleapis.com"
    return f"{location}-aiplatform.googleapis.com"


def check_location(location: str) -> None:
    """Text reaches a model only on an EU endpoint, never `global` (§3.1)."""
    if location == "global" or location not in get_settings().judge.allowed_locations:
        raise AnalyzerError(ErrorClass.JUDGE_API)


def vertex_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The pydantic form as the OpenAPI subset Vertex AI accepts as responseSchema."""
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})

    def convert(node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            return convert(defs[node["$ref"].split("/")[-1]])
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            out = convert(options[0]) if len(options) == 1 else {"anyOf": [convert(o) for o in options]}
            if len(options) < len(node["anyOf"]):
                out["nullable"] = True
            return out
        out: dict[str, Any] = {}
        if "enum" in node:
            out["type"] = "string"
            out["enum"] = [str(v) for v in node["enum"]]
        elif "const" in node:
            out["type"] = "string"
            out["enum"] = [str(node["const"])]
        elif node.get("type") == "object":
            out["type"] = "object"
            out["properties"] = {k: convert(v) for k, v in node.get("properties", {}).items()}
            out["required"] = list(node.get("properties", {}))
        elif node.get("type") == "array":
            out["type"] = "array"
            out["items"] = convert(node.get("items", {}))
            if "maxItems" in node:
                out["maxItems"] = node["maxItems"]
        else:
            out["type"] = node.get("type", "string")
            for k in ("minimum", "maximum"):
                if k in node:
                    out[k] = node[k]
        return out

    return convert(raw)


class BearerToken:
    """Application default credentials, refreshed only when they expire; shared by threads."""

    def __init__(self) -> None:
        self._credentials = None
        self._lock = threading.Lock()

    def __call__(self) -> str:
        import google.auth
        import google.auth.transport.requests

        with self._lock:
            if self._credentials is None:
                self._credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            if not self._credentials.valid:
                self._credentials.refresh(google.auth.transport.requests.Request())
            return self._credentials.token


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter, from the configured base."""
    return get_settings().judge.retry_base_seconds * 2**attempt * (1 + random.random() / 2)


class VertexJudge:
    """REST calls to Vertex AI's generateContent on the configured EU location."""

    def __init__(self, transport: httpx.BaseTransport | None = None, sleep=time.sleep, token=None) -> None:
        s = get_settings().judge
        check_location(s.location)
        self.location = s.location
        self.project = s.vertex_project
        self.http = httpx.Client(timeout=httpx.Timeout(300.0), transport=transport)
        self.sleep = sleep
        self._token = token or BearerToken()

    def url(self, model: str) -> str:
        return (
            f"https://{api_host(self.location)}/v1/projects/{self.project}/locations/{self.location}"
            f"/publishers/google/models/{model}:generateContent"
        )

    def generate(self, model: str, system: str, prompt: str, form: type[BaseModel], usage: Usage) -> BaseModel:
        s = get_settings().judge
        if usage.tokens_before_today + usage.total() > s.daily_token_limit:
            raise TokenLimitError()
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": vertex_schema(form),
            },
        }
        for attempt in range(s.max_retries + 1):
            try:
                resp = self.http.post(
                    self.url(model), json=payload, headers={"Authorization": f"Bearer {self._token()}"}
                )
            except httpx.HTTPError as exc:
                if attempt == s.max_retries:
                    raise JudgeApiError() from exc
                self.sleep(backoff_seconds(attempt))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if resp.status_code == 429:
                    with usage.lock:
                        usage.throttled += 1
                if attempt == s.max_retries:
                    raise JudgeApiError(ErrorClass.JUDGE_THROTTLED if resp.status_code == 429 else None)
                self.sleep(backoff_seconds(attempt))
                continue
            if resp.status_code != 200:
                raise JudgeApiError()
            body = resp.json()
            meta = body.get("usageMetadata") or {}
            usage.add(
                model,
                int(meta.get("promptTokenCount") or 0),
                int(meta.get("candidatesTokenCount") or 0) + int(meta.get("thoughtsTokenCount") or 0),
            )
            try:
                text = body["candidates"][0]["content"]["parts"][0]["text"]
                return form.model_validate(json.loads(text))
            except (KeyError, IndexError, json.JSONDecodeError, ValidationError) as exc:
                raise JudgeOutputError() from exc
        raise JudgeApiError()  # pragma: no cover - the loop always returns or raises


def generate_validated(
    judge: Judge, model: str, system: str, prompt: str, form: type[BaseModel], usage: Usage
) -> BaseModel:
    """An output that fails validation is retried once, then the error class is raised (§6.10)."""
    try:
        return judge.generate(model, system, prompt, form, usage)
    except JudgeOutputError:
        return judge.generate(model, system, prompt, form, usage)


_judge: Judge | None = None


def default_judge() -> Judge:
    global _judge
    if _judge is None:
        if get_settings().env.judge_backend == "fake":
            from conversation_analyzer.judge.fake import FakeJudge

            _judge = FakeJudge()
        else:
            _judge = VertexJudge()
    return _judge


def set_judge(judge: Judge | None) -> None:
    global _judge
    _judge = judge
