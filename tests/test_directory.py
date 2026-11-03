"""The department map the associates indexer writes, read from fake GCS (§8.4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from conversation_analyzer.devtools.synthetic import ensure_bucket, store_department_map
from conversation_analyzer.docs.content import storage_client
from conversation_analyzer.people.directory import Directory, load_directory, split_uri
from conversation_analyzer.settings import get_settings

pytestmark = pytest.mark.emulator

NOW = datetime(2026, 10, 28, 12, tzinfo=UTC)


@pytest.fixture
def pinned(monkeypatch):
    monkeypatch.setenv("CA_NOW", NOW.isoformat())


def _blob():
    bucket, path = split_uri(get_settings().env.department_map_uri)
    ensure_bucket(bucket)
    return storage_client().bucket(bucket).blob(path)


def test_base_function_by_principal():
    d = Directory({"anna@rtbhouse.com": "IT"})
    assert d.base_function("user:Anna@rtbhouse.com ") == "IT"
    assert d.base_function("anna@rtbhouse.com") == "IT"
    assert d.base_function("user:bot@rtbhouse.com") is None
    assert d.base_function(None) is None and d.base_function("") is None


@pytest.mark.parametrize("uri", ["bucket/path.json", "gs://bucket", "gs:///path.json"])
def test_split_uri_rejects_malformed(uri):
    with pytest.raises(ValueError):
        split_uri(uri)


def test_loads_a_fresh_map(pinned):
    store_department_map({"anna@rtbhouse.com": "IT", "jan@rtbhouse.com": ""}, NOW - timedelta(minutes=50))
    d = load_directory()
    assert d is not None and d.departments == {"anna@rtbhouse.com": "IT", "jan@rtbhouse.com": ""}


def test_a_stale_map_is_unavailable(pinned):
    max_age = get_settings().people_directory.max_age_hours
    store_department_map({"anna@rtbhouse.com": "IT"}, NOW - timedelta(hours=max_age, minutes=1))
    assert load_directory() is None


def test_a_missing_map_is_unavailable(pinned):
    _blob().upload_from_string("x")
    _blob().delete()
    assert load_directory() is None


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        json.dumps([]),
        json.dumps({"generated_at": NOW.isoformat(), "count": 0, "departments": {}}),
        json.dumps({"generated_at": NOW.isoformat(), "count": 2, "departments": {"a@rtbhouse.com": "IT"}}),
        json.dumps({"generated_at": NOW.isoformat(), "count": 1, "departments": {"a@rtbhouse.com": 7}}),
        json.dumps({"count": 1, "departments": {"a@rtbhouse.com": "IT"}}),
        json.dumps({"generated_at": "2026-10-28T12:00:00", "count": 1, "departments": {"a@rtbhouse.com": "IT"}}),
    ],
)
def test_a_malformed_map_is_unavailable(pinned, payload):
    _blob().upload_from_string(payload)
    assert load_directory() is None
