"""Error classes and Sentry reporting with the class only: no messages, locals or request bodies (§12.13)."""

from __future__ import annotations

from typing import Any

import sentry_sdk

from conversation_analyzer.settings import get_settings
from conversation_analyzer.vocab import ErrorClass


class AnalyzerError(Exception):
    """An error with a closed-list class; its message is never logged or reported."""

    error_class = ErrorClass.UNEXPECTED

    def __init__(self, error_class: ErrorClass | None = None) -> None:
        super().__init__()
        if error_class is not None:
            self.error_class = error_class


class LeakGuardError(AnalyzerError):
    error_class = ErrorClass.LEAK_GUARD


class JudgeOutputError(AnalyzerError):
    error_class = ErrorClass.JUDGE_INVALID_OUTPUT


class JudgeApiError(AnalyzerError):
    error_class = ErrorClass.JUDGE_API


class TokenLimitError(AnalyzerError):
    error_class = ErrorClass.TOKEN_LIMIT


def classify(exc: BaseException) -> ErrorClass:
    if isinstance(exc, AnalyzerError):
        return exc.error_class
    if isinstance(exc, TimeoutError):
        return ErrorClass.TIMEOUT
    name = type(exc).__module__
    if name.startswith("google.cloud.bigquery") or name.startswith("google.api_core"):
        return ErrorClass.BIGQUERY
    return ErrorClass.UNEXPECTED


def scrub_event(event: dict[str, Any], _hint: Any = None) -> dict[str, Any]:
    """Keep only the error class and code locations of a Sentry event."""
    clean: dict[str, Any] = {
        k: event[k] for k in ("event_id", "timestamp", "platform", "level", "release", "environment") if k in event
    }
    tags = event.get("tags") or {}
    clean["tags"] = {k: v for k, v in tags.items() if k in ("error_class", "job")}
    exceptions = (event.get("exception") or {}).get("values") or []
    clean_values = []
    for exc in exceptions:
        frames = (exc.get("stacktrace") or {}).get("frames") or []
        clean_values.append(
            {
                "type": exc.get("type"),
                "value": "",
                "stacktrace": {
                    "frames": [
                        {k: f[k] for k in ("filename", "function", "lineno", "module") if k in f} for f in frames
                    ]
                },
            }
        )
    if clean_values:
        clean["exception"] = {"values": clean_values}
    if "error_class" in clean["tags"]:
        clean["message"] = clean["tags"]["error_class"]
    return clean


def init_sentry(job: str) -> None:
    dsn = get_settings().env.sentry_dsn
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        release=get_settings().env.code_version,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        max_breadcrumbs=0,
        default_integrations=False,
        before_send=scrub_event,
    )
    sentry_sdk.set_tag("job", job)


def report(exc: BaseException) -> ErrorClass:
    """Report an exception to Sentry as its error class only, and return that class."""
    error_class = classify(exc)
    if get_settings().env.sentry_dsn:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("error_class", error_class.value)
            sentry_sdk.capture_exception(exc)
    return error_class
