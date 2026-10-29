"""Tests run against the local environment only (local.env): emulator, fake GCS, stubs, fake judge."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from datetime import datetime
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


SLOW_EMULATOR_SECONDS = 0.6


def _emulator_latency() -> float:
    from conversation_analyzer.bq.client import execute

    started = time.monotonic()
    for _ in range(3):
        execute("SELECT 1")
    return (time.monotonic() - started) / 3


def _restart_emulator() -> None:
    """The emulator slows down as its job history grows; a restart empties it (and every table)."""
    subprocess.run(["docker-compose", "restart", "bigquery"], cwd=ROOT, check=True, capture_output=True)
    for _ in range(60):
        if _up(9050):
            break
        time.sleep(0.5)


@pytest.fixture(scope="session")
def emulator() -> None:
    if not _up(9050):
        pytest.fail("BigQuery emulator is not running: make up")
    from conversation_analyzer.bq.init import create_all

    create_all()


@pytest.fixture(autouse=True, scope="module")
def _fresh_emulator(request: pytest.FixtureRequest) -> None:
    """Before each emulator test module: restart the emulator if it has become slow."""
    marks = getattr(request.module, "pytestmark", [])
    if not any(m.name == "emulator" for m in (marks if isinstance(marks, list) else [marks])) or not _up(9050):
        return
    if _emulator_latency() > SLOW_EMULATOR_SECONDS:
        from conversation_analyzer.bq.init import create_all

        _restart_emulator()
        create_all()


def wipe(*tables) -> None:
    """Empty the given tables (all tables when none are given), so a test starts from nothing."""
    from conversation_analyzer.bq.client import execute, tbl
    from conversation_analyzer.bq.external import EXTERNAL_TABLES
    from conversation_analyzer.bq.schema import TABLES

    # One script, not one job per table: every job slows the emulator down for the rest of the session.
    execute("; ".join(f"DELETE FROM {tbl(t)} WHERE TRUE" for t in tables or (*TABLES, *EXTERNAL_TABLES)))


@pytest.fixture
def stubs() -> str:
    if not _up(8088):
        pytest.fail("stub server is not running: make up")
    import httpx

    httpx.post("http://localhost:8088/_test/reset")
    return "http://localhost:8088"


def rows(table, where="TRUE"):
    """Rows read as JSON (the emulator can't return nested repeated structs), with its dates and 0/1 booleans fixed."""
    from conversation_analyzer.bq.client import query, tbl

    out = []
    bools = {c.name for c in table.cols if c.type == "BOOL"}
    dates = {c.name for c in table.cols if c.type == "DATE"}
    for r in query(f"SELECT TO_JSON_STRING(t) AS j FROM {tbl(table)} t WHERE {where}"):
        text = re.sub(r"(?<=[:\[,])(\d{4}-\d{2}-\d{2}(?:[ T][0-9:.+-]+Z?)?)(?=[,}\]])", r'"\1"', r["j"])
        row = json.loads(text)
        for k in dates:
            if isinstance(row.get(k), str):
                row[k] = datetime.fromisoformat(row[k]).date()
        for k in bools:
            if row.get(k) is not None:
                row[k] = bool(row[k])
        out.append(row)
    return out
