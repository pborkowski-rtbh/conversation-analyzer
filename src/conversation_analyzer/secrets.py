"""Secrets from Secret Manager, or from CA_SECRET_* variables in local runs."""

from __future__ import annotations

import os
from functools import cache

from conversation_analyzer.settings import get_settings


@cache
def secret(name: str, project: str | None = None) -> bytes:
    settings = get_settings()
    if settings.env.secrets_backend == "env":
        value = os.environ.get("CA_SECRET_" + name.upper().replace("-", "_"))
        if value is None:
            raise KeyError(name)
        return value.encode()
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{project or settings.env.project}/secrets/{name}/versions/latest"
    return client.access_secret_version(name=path).payload.data


def hash_key() -> bytes:
    return secret(get_settings().secrets.hash_key)


def content_secrets() -> tuple[bytes, bytes]:
    s = get_settings().secrets
    return secret(s.content_key, s.content_project), secret(s.content_salt, s.content_project)
