"""One image, one command per job (§12.3), plus local helpers."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import click

from conversation_analyzer import safe_log
from conversation_analyzer.errors import init_sentry, report
from conversation_analyzer.vocab import ChangeKind


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
@click.option("--judge-version", default=None, help="Directory in judge_versions/ to test; default the current one.")
@click.option("--check", is_flag=True, help="Only check the cases against the scenario minimums (§11.1); no judge.")
def quality_judge_suite(
    passes: int, part: str, limit: int, baseline: str | None, judge_version: str | None, check: bool
) -> None:
    """Run the judge test suite and decide whether a judge change is kept (§11.1-11.3)."""
    if check:
        from conversation_analyzer.suite.cases import load_suite

        suite = load_suite()
        for scenario, (n, minimum) in suite.coverage().items():
            click.echo(f"{scenario:40} {n:4} / {minimum}{'  SHORT' if n < minimum else ''}")
        held_out = sum(c.part == "HELD_OUT" for c in suite.cases)
        click.echo(f"{suite.version}: {len(suite.cases)} cases, {held_out} held out")
        if suite.short():
            raise click.ClickException(f"{len(suite.short())} scenario values are below their minimum")
        return
    from conversation_analyzer.suite.runner import run

    def suite_run() -> None:
        report = run(passes=passes, part=part, limit=limit, baseline=baseline, judge_version=judge_version)
        keys = ("suite_run_id", "decision", "n_cases", "passes", "tuning_distance", "held_out_distance")
        click.echo(" ".join(f"{k}={report[k]}" for k in (*keys, "false_high", "failed_calls", "estimated_usd")))

    _job("quality-judge-suite", suite_run)


@main.command("quality-record")
@click.option("--kind", required=True, type=click.Choice([k.value for k in ChangeKind]), help="e.g. DOCUMENT.")
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


@main.command("dev-load-suite-runs")
@click.argument("reports", nargs=-1, type=click.Path(exists=True, dir_okay=False, path_type=Path))
def dev_load_suite_runs(reports: tuple[Path, ...]) -> None:
    """Local only: write suite runs back from their reports; default every full run in suite_reports/."""
    import json

    from conversation_analyzer.settings import get_settings
    from conversation_analyzer.suite.runner import REPORTS_DIR, load_reports

    if not get_settings().env.emulator:
        raise click.UsageError("dev-load-suite-runs runs only against the emulator")
    paths = list(reports) or [p for p in sorted(REPORTS_DIR.glob("*.json")) if not json.loads(p.read_text())["partial"]]
    for run_id in load_reports(paths):
        click.echo(run_id)


if __name__ == "__main__":
    main()
