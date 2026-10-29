"""Change events of a day from four sources: the log, GitHub, indexer runs and judge versions (§12.9)."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from conversation_analyzer.bq.client import fq, query, tbl
from conversation_analyzer.bq.schema import CHANGE_EVENTS, JUDGE_VERSIONS
from conversation_analyzer.errors import AnalyzerError
from conversation_analyzer.judge.client import BearerToken
from conversation_analyzer.leak_guard import allowed_data_store
from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ChangeKind, ChangeSource, ErrorClass


def event_id(*parts: object) -> str:
    return "evt-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _get(url: str, error: ErrorClass, headers: dict[str, str], params: dict[str, Any] | None = None) -> Any:
    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AnalyzerError(error) from exc


def from_log(day: date, recorded: date) -> list[dict[str, Any]]:
    """Engine, agent, connector and data store changes, from the authorized view over the log."""
    view = fq("log_views", "quality_engine_changes")
    rows = query(f"SELECT day, hour, kind, data_store, change_ref FROM {view} WHERE day = @d", d=day)
    return [
        {
            "event_id": "evt-" + r["change_ref"][:16],
            "day": day,
            "hour": r["hour"],
            "source": ChangeSource.LOG.value,
            "kind": r["kind"],
            "data_store": r["data_store"] if allowed_data_store(r["data_store"]) else None,
            "recorded_day": recorded,
        }
        for r in rows
    ]


def from_github(day: date, recorded: date) -> list[dict[str, Any]]:
    """Commits to the repositories that hold Bolek's prompts and data store settings; messages may name clusters."""
    s = get_settings()
    start = datetime.combine(day, time(), UTC)
    headers = {"Authorization": f"Bearer {s.env.github_token}", "Accept": "application/vnd.github+json"}
    pattern = re.compile(s.github.cluster_ref_pattern)
    out = []
    for repo in s.github.repositories:
        for path, kind in s.github.paths.items():
            params = {"since": start.isoformat(), "until": (start + timedelta(days=1)).isoformat(), "path": path}
            for c in _get(f"{s.env.github_api}/repos/{repo}/commits", ErrorClass.GITHUB, headers, params):
                when = _parse_time(c["commit"]["committer"]["date"])
                if when.date() != day:
                    continue
                clusters = sorted(set(pattern.findall(c["commit"].get("message") or "")))
                out.append(
                    {
                        "event_id": event_id(ChangeSource.GITHUB, repo, c["sha"]),
                        "day": day,
                        "hour": when.hour,
                        "source": ChangeSource.GITHUB.value,
                        "kind": kind,
                        "repository": repo,
                        "commit_sha": c["sha"],
                        "clusters": clusters,
                        "recorded_day": recorded,
                    }
                )
    return out


def from_indexers(day: date, recorded: date) -> list[dict[str, Any]]:
    """Indexer job executions that finished on the day, from the Cloud Run run history of this project."""
    s = get_settings()
    cfg = s.indexer_jobs
    base = f"{s.env.cloud_run_api}/v2/projects/{cfg.project}/locations/{cfg.location}/jobs"
    real = "googleapis.com" in s.env.cloud_run_api
    headers = {"Authorization": f"Bearer {BearerToken()()}"} if real else {}
    out = []
    jobs = _get(base, ErrorClass.CLOUD_RUN, headers, {"pageSize": 500}).get("jobs") or []
    for job in (j["name"].rsplit("/", 1)[-1] for j in jobs):
        if not job.startswith(cfg.name_prefix):
            continue
        executions = _get(f"{base}/{job}/executions", ErrorClass.CLOUD_RUN, headers, {"pageSize": 200})
        for e in executions.get("executions") or []:
            done = e.get("completionTime")
            if not done or _parse_time(done).date() != day:
                continue
            name = e["name"].rsplit("/", 1)[-1]
            out.append(
                {
                    "event_id": event_id(ChangeSource.INDEXER, name),
                    "day": day,
                    "hour": _parse_time(done).hour,
                    "source": ChangeSource.INDEXER.value,
                    "kind": ChangeKind.INDEXER.value,
                    "execution": name,
                    "recorded_day": recorded,
                }
            )
    return out


def from_judge(day: date, recorded: date) -> list[dict[str, Any]]:
    """A judge version used for the first time, and the end of its parallel run (§6.11)."""
    rows = query(
        f"SELECT judge_version, first_used_day, parallel_run_until FROM {tbl(JUDGE_VERSIONS)} "
        "WHERE first_used_day = @d OR parallel_run_until = @p",
        d=day,
        p=day - timedelta(days=1),
    )
    out = []
    for r in rows:
        kind = ChangeKind.JUDGE if r["first_used_day"] == day else ChangeKind.PARALLEL_RUN_END
        out.append(
            {
                "event_id": event_id(ChangeSource.JUDGE, kind, r["judge_version"]),
                "day": day,
                "hour": 0,
                "source": ChangeSource.JUDGE.value,
                "kind": kind.value,
                "judge_version": r["judge_version"],
                "recorded_day": recorded,
            }
        )
    return out


def collect(day: date, recorded: date) -> list[dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    for source in (from_log, from_github, from_indexers, from_judge):
        for e in source(day, recorded):
            events[e["event_id"]] = e
    return list(events.values())


def events_between(first: date, last: date) -> list[dict[str, Any]]:
    """Stored change events of these days, oldest first."""
    return query(
        f"SELECT event_id, day, hour, source, kind, data_store, doc_id, clusters, judge_version "
        f"FROM {tbl(CHANGE_EVENTS)} WHERE day BETWEEN @a AND @b ORDER BY day, hour, event_id",
        a=first,
        b=last,
    )
