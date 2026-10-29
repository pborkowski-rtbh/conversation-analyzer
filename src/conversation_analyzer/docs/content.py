"""Full text of our documents from the content bucket, as the indexers write it (§12.7)."""

from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from google.api_core.exceptions import NotFound

from conversation_analyzer.judge.case import DocRef, DocText
from conversation_analyzer.leak_guard import is_people_directory
from conversation_analyzer.secrets import content_secrets
from conversation_analyzer.settings import get_settings

KDF_ITERATIONS = 1_200_000  # must match the indexers' sink


def content_path(data_store_id: str, uri: str) -> str:
    return f"{data_store_id}/{hashlib.sha256(uri.encode()).hexdigest()}.enc"


def derive_key(key: str, salt: str) -> bytes:
    raw = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt.encode(), iterations=KDF_ITERATIONS).derive(
        key.encode()
    )
    return base64.urlsafe_b64encode(raw)


@lru_cache(maxsize=1)
def fernet() -> Fernet:
    key, salt = content_secrets()
    return Fernet(derive_key(key.decode().strip(), salt.decode().strip()))


@lru_cache(maxsize=1)
def storage_client():
    from google.cloud import storage

    env = get_settings().env
    if env.gcs_endpoint:
        from google.auth.credentials import AnonymousCredentials

        return storage.Client(
            project=env.bq_project,
            credentials=AnonymousCredentials(),
            client_options={"api_endpoint": env.gcs_endpoint},
        )
    return storage.Client(project=get_settings().project)


class ContentReader:
    """Reads and decrypts one document; None when it has no text in the bucket (Drive, people directory, missing)."""

    def __init__(self) -> None:
        self.missing = 0

    def read(self, ref: DocRef) -> DocText | None:
        s = get_settings()
        ds = s.data_store(ref.data_store)
        if ds is None or not ds.has_content or not ref.uri or is_people_directory(ref.data_store, ref.doc_id, ref.uri):
            return None
        blob = storage_client().bucket(s.bucket_for(ds.id)).blob(content_path(ds.id, ref.uri))
        try:
            payload = json.loads(fernet().decrypt(blob.download_as_bytes()))
        except (NotFound, InvalidToken, ValueError):
            self.missing += 1
            return None
        return DocText(
            ref=ref, title=payload.get("title") or "", text=(payload.get("content") or "")[: s.sizes.document_chars]
        )
