"""Tests run against the local environment only (local.env): emulator, fake GCS, stubs, fake judge."""

from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

for line in (ROOT / "local.env").read_text().splitlines():
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ[key] = value  # never inherit real endpoints into tests


def _up(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("localhost", port)) == 0


@pytest.fixture(scope="session")
def emulator() -> None:
    if not _up(9050):
        pytest.fail("BigQuery emulator is not running: make up")
    from conversation_analyzer.bq.init import create_all

    create_all()


def wipe(*tables) -> None:
    """Empty the given tables (all tables when none are given), so a test starts from nothing."""
    from conversation_analyzer.bq.client import execute, tbl
    from conversation_analyzer.bq.external import EXTERNAL_TABLES
    from conversation_analyzer.bq.schema import TABLES

    for table in tables or (*TABLES, *EXTERNAL_TABLES):
        execute(f"DELETE FROM {tbl(table)} WHERE TRUE")


@pytest.fixture
def stubs() -> str:
    if not _up(8088):
        pytest.fail("stub server is not running: make up")
    import httpx

    httpx.post("http://localhost:8088/_test/reset")
    return "http://localhost:8088"
