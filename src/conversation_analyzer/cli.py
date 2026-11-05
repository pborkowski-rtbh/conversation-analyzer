"""One image, one command per job (§12.3), plus local helpers."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import click

from conversation_analyzer import safe_log
from conversation_analyzer.errors import init_sentry, report
from conversation_analyzer.vocab import ChangeKind

IGNORE_GATE = click.option("--ignore-gate", is_flag=True, help="Run even while stage's run gate is closed.")


def _gate_open() -> bool:
    from conversation_analyzer.run_gate import is_open

    return is_open()


def _job(
    name: str,
    fn: Callable[[], object],
    gated: bool = False,
    ignore_gate: bool = False,
    when_closed: Callable[[], object] | None = None,
) -> None:
    init_sentry(name)
    safe_log.log("job_start", job=name)
    try:
        if gated and not ignore_gate and not _gate_open():
            if when_closed is not None:
                when_closed()
            safe_log.log("gate_closed", job=name)
        else:
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
@click.option("--dry-run", is_flag=True, help="Read the window and plan the work; write only the run record, no judge.")
@IGNORE_GATE
def quality_assessor(dry_run: bool, ignore_gate: bool) -> None:
    """Assess the turns in the window (every 10 minutes)."""
    from conversation_analyzer.assessor.run import paused, run

    _job(
        "quality-assessor",
        (lambda: run(dry_run=True)) if dry_run else run,
        gated=True,
        ignore_gate=ignore_gate,
        when_closed=paused,
    )


@main.command("quality-monitor")
@IGNORE_GATE
def quality_monitor(ignore_gate: bool) -> None:
    """Pipeline health, HIGH cluster alerts, acknowledgements (every 10 minutes, 5 after the assessor)."""
    from conversation_analyzer.reporting.monitor import run

    _job("quality-monitor", run, gated=True, ignore_gate=ignore_gate)


@main.command("quality-daily")
@click.option("--day", default=None, help="Day to compute (YYYY-MM-DD); default yesterday (UTC).")
@IGNORE_GATE
def quality_daily(day: str | None, ignore_gate: bool) -> None:
    """Change events, daily metrics, anomalies, release impact (05:00 UTC)."""
    from conversation_analyzer.reporting.daily import run

    _job("quality-daily", lambda: run(day), gated=True, ignore_gate=ignore_gate)


@main.command("quality-weekly")
@click.option("--week", default=None, help="Monday of the week to build (YYYY-MM-DD); default last week.")
@IGNORE_GATE
def quality_weekly(week: str | None, ignore_gate: bool) -> None:
    """Problem clusters, document stats, eval documents, digest (Mondays 06:00 UTC)."""
    from conversation_analyzer.reporting.weekly import run

    _job("quality-weekly", lambda: run(week), gated=True, ignore_gate=ignore_gate)


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
@click.option("--check", is_flag=True, help="Only compare the live schema with bq/schema.py; exit 1 on a difference.")
def db_init(check: bool) -> None:
    """Create all datasets, tables and views."""
    if check:
        from conversation_analyzer.bq.check import differences

        found = differences()
        for d in found:
            click.echo(d)
        safe_log.log("db_check", differences=len(found))
        if found:
            sys.exit(1)
        return
    from conversation_analyzer.bq.init import create_all

    created = create_all()
    safe_log.log("db_init", tables=len(created))


@main.command("leak-audit")
@click.option("--since", required=True, help="First day (YYYY-MM-DD) of the partitions to read back.")
def leak_audit(since: str) -> None:
    """Read stored rows back through the leak guard and a string-length check; print counts only, exit 1 on any."""
    from datetime import date

    from conversation_analyzer.bq.audit import audit

    counts = audit(date.fromisoformat(since))
    click.echo(f"{'table':34} {'rows':>8} {'rejected':>9} {'dropped':>8} {'too_long':>9}")
    for c in counts:
        click.echo(f"{c.table:34} {c.rows:8} {c.rejected:9} {c.dropped:8} {c.too_long:9}")
    findings = sum(c.findings for c in counts)
    safe_log.log("leak_audit", tables=len(counts), rows=sum(c.rows for c in counts), findings=findings)
    if findings:
        sys.exit(1)


@main.group("run-gate")
def run_gate() -> None:
    """Stage's run gate: scheduled jobs run only while it is open (deployment-plan.md §3)."""


@run_gate.command("resume")
@click.option("--hours", required=True, type=click.IntRange(1, 24), help="Hours to stay open (1-24).")
def run_gate_resume(hours: int) -> None:
    """Open the gate for HOURS from now."""
    from conversation_analyzer import run_gate as gate

    click.echo(f"open until {gate.resume(hours).isoformat()}")


@run_gate.command("pause")
def run_gate_pause() -> None:
    """Close the gate now."""
    from conversation_analyzer import run_gate as gate

    gate.pause()
    click.echo("closed")


@run_gate.command("status")
def run_gate_status() -> None:
    """Show whether the gate is open and until when."""
    from conversation_analyzer import run_gate as gate
    from conversation_analyzer.settings import get_settings

    if not get_settings().env.run_gate_uri:
        click.echo("no run gate (CA_RUN_GATE_URI unset): always open")
        return
    until = gate.open_until()
    click.echo(f"{'open' if gate.is_open() else 'closed'} (open_until {until.isoformat() if until else 'unset'})")


@main.command("dev-seed")
@click.option("--now", default=None, help="Time the synthetic window ends (ISO); default now (or CA_NOW).")
def dev_seed(now: str | None) -> None:
    """Local only: write the synthetic scenario (log rows and documents) into the emulator."""
    from datetime import datetime

    from conversation_analyzer.devtools import scenario
    from conversation_analyzer.settings import get_settings
    from conversation_analyzer.settings import now as current

    if not get_settings().env.emulator:
        raise click.UsageError("dev-seed writes synthetic rows and runs only against the emulator")
    scenario.seed(datetime.fromisoformat(now) if now else current())
    safe_log.log("dev_seed", turns=len(scenario.turns()))


@main.command("dev-seed-dashboard")
@click.option("--today", default=None, help="Day after the last mocked day (YYYY-MM-DD); default today (or CA_NOW).")
def dev_seed_dashboard(today: str | None) -> None:
    """Local only: write eight weeks of mocked metrics rows for the local Grafana dashboard."""
    from datetime import date

    from conversation_analyzer.devtools import dashboard_mock
    from conversation_analyzer.settings import get_settings
    from conversation_analyzer.settings import now as current

    if not get_settings().env.emulator:
        raise click.UsageError("dev-seed-dashboard writes mocked rows and runs only against the emulator")
    counts = dashboard_mock.seed(date.fromisoformat(today) if today else current().date())
    safe_log.log("dev_seed_dashboard", **counts)


@main.command("dashboard-check")
@click.argument("dashboard", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--var", "variables", multiple=True, help="A variable's value, name=value; default its saved value.")
@click.option("--from", "start", default=None, help="Start of the time range (now-56d, ISO); default the dashboard's.")
@click.option("--to", "end", default=None, help="End of the time range; default the dashboard's.")
@click.option(
    "--allow-empty", is_flag=True, help="Fail on query errors only (the demo has too few turns to fill panels)."
)
def dashboard_check(
    dashboard: Path, variables: tuple[str, ...], start: str | None, end: str | None, allow_empty: bool
) -> None:
    """Local only: run every panel's SQL of a Grafana dashboard file on the emulator; errors and empty panels fail."""
    from conversation_analyzer.devtools import dashboard_check as dc
    from conversation_analyzer.settings import get_settings
    from conversation_analyzer.settings import now as current

    if not get_settings().env.emulator:
        raise click.UsageError("dashboard-check runs only against the emulator")
    spec = dc.load(dashboard)
    values = dc.defaults(spec)
    for v in variables:
        name, sep, value = v.partition("=")
        if not sep:
            raise click.UsageError(f"--var takes name=value, got {v!r}")
        values[name] = value
    when = current()
    window = spec.get("time", {})
    a = dc.time_point(start or window.get("from", "now-7d"), when)
    b = dc.time_point(end or window.get("to", "now"), when)
    results = dc.check(spec, values, a, b)
    for r in results:
        state = "ERROR" if r.error else ("ok" if r.rows else ("EMPTY" if r.query.required else "empty"))
        click.echo(f"{state:5} {r.rows if r.rows is not None else '-':>6}  {r.query.title} [{r.query.ref}]")
        if r.error:
            click.echo(f"      {r.error}")
    failed = [r for r in results if r.error or not (r.ok or allow_empty)]
    click.echo(f"{len(results) - len(failed)} of {len(results)} queries passed ({a.date()} to {b.date()})")
    if failed:
        sys.exit(1)


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
