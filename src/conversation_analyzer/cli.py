"""One image, one command per job (§12.3), plus local helpers."""

from __future__ import annotations

import sys
from collections.abc import Callable

import click

from conversation_analyzer import safe_log
from conversation_analyzer.errors import init_sentry, report


def _job(name: str, fn: Callable[[], object]) -> None:
    init_sentry(name)
    safe_log.log("job_start", job=name)
    try:
        fn()
    except Exception as exc:  # every failure leaves as an error class only
        error_class = report(exc)
        safe_log.log("job_failed", severity="ERROR", job=name, error_class=error_class.value)
        sys.exit(1)
    safe_log.log("job_done", job=name)


@click.group()
def main() -> None:
    """Conversation Analyzer jobs and local tools."""


@main.command("quality-assessor")
def quality_assessor() -> None:
    """Assess the turns in the window (every 10 minutes)."""
    from conversation_analyzer.assessor.run import run

    _job("quality-assessor", run)


@main.command("quality-monitor")
def quality_monitor() -> None:
    """Pipeline health, HIGH cluster alerts, acknowledgements (every 10 minutes, 5 after the assessor)."""
    from conversation_analyzer.reporting.monitor import run

    _job("quality-monitor", run)


@main.command("quality-daily")
@click.option("--day", default=None, help="Day to compute (YYYY-MM-DD); default yesterday (UTC).")
def quality_daily(day: str | None) -> None:
    """Change events, daily metrics, anomalies, release impact (05:00 UTC)."""
    from conversation_analyzer.reporting.daily import run

    _job("quality-daily", lambda: run(day))


@main.command("quality-weekly")
@click.option("--week", default=None, help="Monday of the week to build (YYYY-MM-DD); default last week.")
def quality_weekly(week: str | None) -> None:
    """Problem clusters, document stats, eval documents, digest (Mondays 06:00 UTC)."""
    from conversation_analyzer.reporting.weekly import run

    _job("quality-weekly", lambda: run(week))


@main.command("quality-judge-suite")
@click.option("--passes", default=3, show_default=True)
@click.option("--part", type=click.Choice(["all", "tuning", "held_out"]), default="all", show_default=True)
@click.option("--limit", default=0, help="Run only the first N cases (0 = all).")
@click.option("--baseline", default=None, help="Suite run ID to compare with; default the last kept run.")
def quality_judge_suite(passes: int, part: str, limit: int, baseline: str | None) -> None:
    """Run the judge test suite and decide whether a judge change is kept (§11.1-11.3)."""
    from conversation_analyzer.suite.runner import run

    _job("quality-judge-suite", lambda: run(passes=passes, part=part, limit=limit, baseline=baseline))


@main.command("quality-record")
@click.option("--kind", required=True, help="Change kind, e.g. DOCUMENT or AQR_REBASE.")
@click.option("--day", default=None, help="Day of the change (YYYY-MM-DD); default today.")
@click.option("--hour", default=None, type=int)
@click.option("--doc-id", default=None)
@click.option("--data-store", default=None)
@click.option("--cluster", "clusters", multiple=True, help="Problem cluster the change should fix (repeatable).")
def quality_record(
    kind: str, day: str | None, hour: int | None, doc_id: str | None, data_store: str | None, clusters: tuple[str, ...]
) -> None:
    """Record a change event that no source collects on its own (§12.3)."""
    from conversation_analyzer.reporting.record import record

    _job("quality-record", lambda: record(kind, day, hour, doc_id, data_store, list(clusters)))


@main.command("quality-alert-lookup")
@click.option("--alert", "alert_id", required=True, help="Alert ID from a Slack message, e.g. alert-1a2b3c4d5e6f7a8b.")
def quality_alert_lookup(alert_id: str) -> None:
    """Show an alert and its session segments, with the grades shown then and the latest ones (§7.7)."""
    import json

    from conversation_analyzer.reporting.lookup import lookup

    found = lookup(alert_id)
    if found is None:
        raise click.ClickException("no such alert")
    click.echo(json.dumps(found, default=str, indent=2))


@main.command("db-init")
def db_init() -> None:
    """Create all datasets, tables and views."""
    from conversation_analyzer.bq.init import create_all

    created = create_all()
    safe_log.log("db_init", tables=len(created))


@main.command("dev-seed")
@click.option("--now", default=None, help="Time the synthetic window ends (ISO); default now (or CA_NOW).")
def dev_seed(now: str | None) -> None:
    """Local only: write the synthetic scenario (log rows, documents, chunks) into the emulator."""
    from datetime import datetime

    from conversation_analyzer.devtools import scenario
    from conversation_analyzer.settings import get_settings
    from conversation_analyzer.settings import now as current

    if not get_settings().env.emulator:
        raise click.UsageError("dev-seed writes synthetic rows and runs only against the emulator")
    scenario.seed(datetime.fromisoformat(now) if now else current())
    safe_log.log("dev_seed", turns=len(scenario.turns()))


if __name__ == "__main__":
    main()
