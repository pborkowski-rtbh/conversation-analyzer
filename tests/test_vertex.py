"""Vertex AI clients with mocked transports: EU endpoints only, backoff, token accounting, output validation."""

from __future__ import annotations

import json
import time
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel, Field

from conversation_analyzer.errors import AnalyzerError, JudgeApiError, JudgeOutputError, TokenLimitError
from conversation_analyzer.judge import client as jc
from conversation_analyzer.judge.client import Usage, VertexJudge, api_host, check_location, vertex_schema
from conversation_analyzer.judge.forms import Stage1Form, Stage2Form
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ErrorClass


class Inner(BaseModel):
    name: str


class Form(BaseModel):
    label: Literal["A", "B"]
    score: int | None = Field(ge=1, le=5)
    items: list[Inner] = Field(max_length=2)
    either: int | str


def answer(payload: dict, usage: dict | None = None) -> httpx.Response:
    body = {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}
    if usage is not None:
        body["usageMetadata"] = usage
    return httpx.Response(200, json=body)


def judge_with(responses: list, sleeps: list | None = None) -> tuple[VertexJudge, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    sleeps = sleeps if sleeps is not None else []
    return VertexJudge(transport=httpx.MockTransport(handler), sleep=sleeps.append, token=lambda: "tok"), seen


def test_api_host_and_location():
    assert api_host("eu") == "aiplatform.eu.rep.googleapis.com"
    assert api_host("europe-west4") == "europe-west4-aiplatform.googleapis.com"
    check_location("eu")
    for bad in ("global", "us-central1"):
        with pytest.raises(AnalyzerError):
            check_location(bad)


def test_vertex_schema_converts_refs_enums_nullable_and_unions():
    schema = vertex_schema(Form)
    props = schema["properties"]
    assert schema["type"] == "object" and schema["required"] == ["label", "score", "items", "either"]
    assert props["label"] == {"type": "string", "enum": ["A", "B"]}
    assert props["score"] == {"type": "integer", "minimum": 1, "maximum": 5, "nullable": True}
    assert props["items"]["maxItems"] == 2 and props["items"]["items"]["properties"]["name"] == {"type": "string"}
    assert props["either"] == {"anyOf": [{"type": "integer"}, {"type": "string"}]}
    # the real forms convert without leftover JSON-schema keys
    for form in (Stage1Form, Stage2Form):
        assert "$ref" not in json.dumps(vertex_schema(form))


def test_const_becomes_single_enum():
    class C(BaseModel):
        kind: Literal["ONLY"]

    assert vertex_schema(C)["properties"]["kind"] == {"type": "string", "enum": ["ONLY"]}


def test_generate_posts_eu_request_and_counts_tokens():
    payload = {"label": "A", "score": 3, "items": [{"name": "x"}], "either": 1}
    judge, seen = judge_with(
        [answer(payload, {"promptTokenCount": 10, "candidatesTokenCount": 4, "thoughtsTokenCount": 2})]
    )
    usage = Usage()
    form = judge.generate("gemini-3.8-flash", "system", "prompt", Form, usage)
    assert form.label == "A"
    req = seen[0]
    assert req.url.host == "aiplatform.eu.rep.googleapis.com"
    assert "/locations/eu/publishers/google/models/gemini-3.8-flash:generateContent" in req.url.path
    assert req.headers["Authorization"] == "Bearer tok"
    body = json.loads(req.content)
    assert body["generationConfig"]["temperature"] == 0
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert usage.rows() == [{"model": "gemini-3.8-flash", "input_tokens": 10, "output_tokens": 6}]
    assert usage.total() == 16


def test_throttling_backs_off_then_succeeds():
    payload = {"label": "B", "score": None, "items": [], "either": "x"}
    sleeps: list = []
    judge, _ = judge_with([httpx.Response(429), httpx.Response(503), httpx.ConnectError("x"), answer(payload)], sleeps)
    usage = Usage()
    assert judge.generate("m", "s", "p", Form, usage).score is None
    assert usage.throttled == 1 and len(sleeps) == 3
    assert sleeps[0] < sleeps[1]  # exponential


def test_retries_exhausted_raise_error_class():
    n = get_settings().judge.max_retries + 1
    judge, _ = judge_with([httpx.Response(429)] * n)
    with pytest.raises(JudgeApiError) as exc:
        judge.generate("m", "s", "p", Form, Usage())
    assert exc.value.error_class == ErrorClass.JUDGE_THROTTLED
    judge, _ = judge_with([httpx.Response(500)] * n)
    with pytest.raises(JudgeApiError) as exc:
        judge.generate("m", "s", "p", Form, Usage())
    assert exc.value.error_class == ErrorClass.JUDGE_API
    judge, _ = judge_with([httpx.ReadTimeout("t")] * n)
    with pytest.raises(JudgeApiError):
        judge.generate("m", "s", "p", Form, Usage())


def test_client_error_is_not_retried():
    judge, seen = judge_with([httpx.Response(400)])
    with pytest.raises(JudgeApiError):
        judge.generate("m", "s", "p", Form, Usage())
    assert len(seen) == 1


@pytest.mark.parametrize(
    "response",
    [
        answer({"label": "C", "score": 1, "items": [], "either": 1}),  # not in the closed list
        httpx.Response(200, json={"candidates": []}),
        httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}),
    ],
)
def test_invalid_output_raises_output_error(response):
    judge, _ = judge_with([response])
    with pytest.raises(JudgeOutputError):
        judge.generate("m", "s", "p", Form, Usage())


def test_daily_token_limit_stops_before_calling():
    judge, seen = judge_with([])
    usage = Usage(tokens_before_today=get_settings().judge.daily_token_limit + 1)
    with pytest.raises(TokenLimitError):
        judge.generate("m", "s", "p", Form, usage)
    assert not seen


def test_generate_validated_retries_once():
    good = {"label": "A", "score": 1, "items": [], "either": 1}
    judge, seen = judge_with([answer({"label": "Z"}), answer(good)])
    assert jc.generate_validated(judge, "m", "s", "p", Form, Usage()).label == "A"
    judge, _ = judge_with([answer({"label": "Z"}), answer({"label": "Z"})])
    with pytest.raises(JudgeOutputError):
        jc.generate_validated(judge, "m", "s", "p", Form, Usage())


def test_judge_refuses_global(monkeypatch):
    monkeypatch.setattr(get_settings().judge, "location", "global")
    with pytest.raises(AnalyzerError):
        VertexJudge(token=lambda: "t")


def test_default_judge_follows_backend(monkeypatch):
    from conversation_analyzer.judge.fake import FakeJudge

    jc.set_judge(None)
    assert isinstance(jc.default_judge(), FakeJudge)
    jc.set_judge(None)
    monkeypatch.setattr(get_settings().env, "judge_backend", "vertex")
    assert isinstance(jc.default_judge(), VertexJudge)
    jc.set_judge(None)


def test_bearer_token_refreshes_only_when_invalid(monkeypatch):
    class Creds:
        valid = False
        token = "abc"
        refreshed = 0

        def refresh(self, _request):
            self.refreshed += 1
            self.valid = True

    creds = Creds()
    import google.auth

    monkeypatch.setattr(google.auth, "default", lambda scopes: (creds, "p"))
    token = jc.BearerToken()
    assert token() == "abc" and token() == "abc"
    assert creds.refreshed == 1


def test_deadline_passed_makes_no_call():
    judge, seen = judge_with([])
    usage = Usage(deadline=time.monotonic() - 1)
    with pytest.raises(JudgeApiError) as exc:
        judge.generate("m", "s", "p", Form, usage)
    assert exc.value.error_class == ErrorClass.TIMEOUT and not seen


def test_deadline_caps_the_request_timeout_and_the_backoff():
    payload = {"label": "A", "score": 2, "items": [], "either": 1}
    judge, seen = judge_with([answer(payload)])
    judge.generate("m", "s", "p", Form, Usage(deadline=time.monotonic() + 30))
    assert seen[0].extensions["timeout"]["read"] <= 30
    judge, _ = judge_with([httpx.ReadTimeout("t")])
    with pytest.raises(JudgeApiError) as exc:  # cut off by the deadline: no retry
        judge.generate("m", "s", "p", Form, Usage(deadline=time.monotonic() + 30))
    assert exc.value.error_class == ErrorClass.TIMEOUT
    sleeps: list = []
    judge, _ = judge_with([httpx.Response(503)], sleeps)
    with pytest.raises(JudgeApiError) as exc:  # the backoff would pass the deadline
        judge.generate("m", "s", "p", Form, Usage(deadline=time.monotonic() + 0.5))
    assert exc.value.error_class == ErrorClass.TIMEOUT and not sleeps
    assert Usage().remaining() is None
