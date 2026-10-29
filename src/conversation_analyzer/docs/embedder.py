"""Embeddings for the document index: a multilingual model in an EU region, or a deterministic fake locally."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import httpx

from conversation_analyzer.errors import AnalyzerError
from conversation_analyzer.judge.client import api_host, check_location
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

    def __init__(self, transport: httpx.BaseTransport | None = None, token=None) -> None:
        s = get_settings()
        check_location(s.embedding.location)
        self.model = s.embedding.model
        self.url = (
            f"https://{api_host(s.embedding.location)}/v1/projects/{s.judge.vertex_project}/locations/"
            f"{s.embedding.location}/publishers/google/models/{self.model}:predict"
        )
        self.http = httpx.Client(timeout=60.0, transport=transport)
        self._token = token

    def _bearer(self) -> str:
        if self._token is None:
            import google.auth
            import google.auth.transport.requests

            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(google.auth.transport.requests.Request())
            return creds.token
        return self._token()

    def embed(self, texts: list[str], task: str = "RETRIEVAL_QUERY") -> list[list[float]]:
        out: list[list[float]] = []
        dims = get_settings().embedding.dimensions
        for i in range(0, len(texts), 5):
            batch = [{"content": t, "task_type": task} for t in texts[i : i + 5]]
            resp = self.http.post(
                self.url,
                json={"instances": batch, "parameters": {"outputDimensionality": dims}},
                headers={"Authorization": f"Bearer {self._bearer()}"},
            )
            if resp.status_code != 200:
                raise AnalyzerError(ErrorClass.EMBEDDING_API)
            out.extend(p["embeddings"]["values"] for p in resp.json()["predictions"])
        return out


def default_embedder() -> Embedder:
    return FakeEmbedder() if get_settings().env.embedding_backend == "fake" else VertexEmbedder()
