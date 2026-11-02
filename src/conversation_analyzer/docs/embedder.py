"""Embeddings for the document index: a multilingual model in an EU region, or a deterministic fake locally."""

from __future__ import annotations

import hashlib
import math
import re
import time
from typing import Protocol

import httpx

from conversation_analyzer.errors import AnalyzerError
from conversation_analyzer.judge.client import BearerToken, api_host, backoff_seconds, check_location
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ErrorClass


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str], task: str) -> list[list[float]]: ...


class FakeEmbedder:
    """Bag of hashed words: similar texts get similar vectors, with no model call."""

    model = "fake-embedding"

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions or get_settings().embedding.dimensions

    def embed(self, texts: list[str], task: str = "RETRIEVAL_QUERY") -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dimensions
            for word in re.findall(r"\w{3,}", text.lower()):
                vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dimensions] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([round(v / norm, 6) for v in vec])
        return out


class VertexEmbedder:
    """text-multilingual-embedding models through Vertex AI's predict endpoint in an EU region."""

    BATCH = 5

    def __init__(self, transport: httpx.BaseTransport | None = None, token=None, sleep=time.sleep) -> None:
        s = get_settings()
        check_location(s.embedding.location)
        self.model = s.embedding.model
        self.url = (
            f"https://{api_host(s.embedding.location)}/v1/projects/{s.judge.vertex_project}/locations/"
            f"{s.embedding.location}/publishers/google/models/{self.model}:predict"
        )
        self.http = httpx.Client(timeout=60.0, transport=transport)
        self._token = token or BearerToken()
        self.sleep = sleep

    def _post(self, payload: dict) -> httpx.Response:
        retries = get_settings().judge.max_retries
        for attempt in range(retries + 1):
            try:
                resp = self.http.post(self.url, json=payload, headers={"Authorization": f"Bearer {self._token()}"})
            except httpx.HTTPError as exc:
                if attempt == retries:
                    raise AnalyzerError(ErrorClass.EMBEDDING_API) from exc
            else:
                if resp.status_code == 200:
                    return resp
                if (resp.status_code != 429 and resp.status_code < 500) or attempt == retries:
                    raise AnalyzerError(ErrorClass.EMBEDDING_API)
            self.sleep(backoff_seconds(attempt))
        raise AnalyzerError(ErrorClass.EMBEDDING_API)  # pragma: no cover - the loop always returns or raises

    def embed(self, texts: list[str], task: str = "RETRIEVAL_QUERY") -> list[list[float]]:
        out: list[list[float]] = []
        dims = get_settings().embedding.dimensions
        for i in range(0, len(texts), self.BATCH):
            batch = [{"content": t, "task_type": task} for t in texts[i : i + self.BATCH]]
            resp = self._post({"instances": batch, "parameters": {"outputDimensionality": dims}})
            try:
                out.extend(p["embeddings"]["values"] for p in resp.json()["predictions"])
            except (KeyError, TypeError, ValueError) as exc:
                raise AnalyzerError(ErrorClass.EMBEDDING_API) from exc
        return out


def default_embedder() -> Embedder:
    return FakeEmbedder() if get_settings().env.embedding_backend == "fake" else VertexEmbedder()
