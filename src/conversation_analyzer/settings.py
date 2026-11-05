"""Settings: tunables from config/settings.yaml (§12.14), the same in every project; the job's own project from CA_*."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]


class Secrets(BaseModel):
    hash_key: str  # in the job's own project, so stage and prod keys differ
    content_project: str
    content_key: str
    content_salt: str


class Datasets(BaseModel):
    log: str
    turns: str
    metrics: str
    log_views: str
    evals: str


OWN_DATASETS = ("turns", "metrics", "log_views")  # in the job's own project; the others are read from prod's


class Switch(BaseModel):
    enabled: bool = True


class LeakAudit(BaseModel):
    max_string_chars: int
    max_link_chars: int


class Evaluator(BaseModel):
    prompt_prefix: str
    question_marker: str
    accounts: list[str] = Field(default_factory=list)


class Canary(BaseModel):
    planted_share: float


class Timing(BaseModel):
    eligible_after_minutes: int
    hard_limit_minutes: int
    assessment_target_minutes: int
    segment_idle_close_minutes: int
    window_read_minutes: int
    window_alert_minutes: int
    stop_new_calls_after_seconds: int
    run_time_limit_seconds: int
    write_reserve_seconds: int
    no_run_alert_minutes: int
    feedback_after_window_fallback: bool

    @model_validator(mode="after")
    def _calls_stop_before_deadline(self) -> Timing:
        if self.stop_new_calls_after_seconds >= self.run_time_limit_seconds - self.write_reserve_seconds:
            raise ValueError("stop_new_calls_after_seconds must leave time before the judge deadline")
        return self


class Sizes(BaseModel):
    too_large_chars: int
    context_chars: int
    document_chars: int
    evidence_check_documents: int
    stage2_linked_documents: int
    stage2_max_claims: int


class Pace(BaseModel):
    max_turns: int
    window_minutes: int


class Judge(BaseModel):
    location: str
    allowed_locations: list[str]
    current_version: str
    previous_version: str | None = None
    parallel_run_until: date | None = None
    concurrency: int
    max_retries: int
    retry_base_seconds: float
    second_model_share: float
    daily_token_limit: int


class Anomaly(BaseModel):
    jump_noise_levels: float
    cusum_slack: float
    cusum_limit: float
    reference_days: int
    min_reference_days: int
    min_day_turns: int
    change_event_lookback_hours: int


class ReleaseImpact(BaseModel):
    weekdays: int
    z: float


class LogGap(BaseModel):
    reference_weeks: int
    min_ratio: float
    min_expected: int


class Metrics(BaseModel):
    min_slice_size: int
    go_live_day: date | None = None
    baseline_weeks: int
    coverage_target: float
    anomaly: Anomaly
    release_impact: ReleaseImpact
    log_gap: LogGap


class Strata(BaseModel):
    intent_families: dict[str, list[str]]
    data_store_families: dict[str, list[str]]
    department_families: dict[str, list[str]]  # family -> base_function values; the rest are OTHER (§8.4)
    department_min_associates: int  # privacy floor: a smaller family is stored as OTHER

    @model_validator(mode="after")
    def _one_family_each(self) -> Strata:
        members = [m for ms in self.department_families.values() for m in ms]
        if len(members) != len(set(members)):
            raise ValueError("a base_function belongs to more than one department family")
        return self


class Alerts(BaseModel):
    high_alert_bar: int
    quality_channel: str
    alerts_channel: str
    ack_emoji: str


class Clusters(BaseModel):
    severity_weights: dict[str, int]
    top_n: int
    trend_weeks: int
    close_ratio: float
    close_weeks: int
    reliability_threshold: float


class Digest(BaseModel):
    best_n: int
    growth_ratio: float


class EvalDocuments(BaseModel):
    anchor_questions: int
    anchor_min_per_data_store: int
    focus_questions_per_cluster: int


class Suite(BaseModel):
    max_usd_per_run: float
    prices_usd_per_million: dict[str, tuple[float, float]]

    def usd(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimated cost of tokens on a model; unknown models use the `default` prices."""
        inp, out = self.prices_usd_per_million.get(model) or self.prices_usd_per_million["default"]
        return (input_tokens * inp + output_tokens * out) / 1_000_000


class GitHub(BaseModel):
    repositories: list[str]
    paths: dict[str, str]  # path in the repositories to the change kind of commits touching it
    cluster_ref_pattern: str


class IndexerJobs(BaseModel):
    project: str
    location: str
    name_prefix: str


class DataStore(BaseModel):
    id: str
    topic: str
    hosts: list[str]
    path_prefix: str | None = None
    has_content: bool
    bucket: str | None = None


class PeopleDirectory(BaseModel):
    data_store_ids: list[str]
    data_store_prefixes: list[str]
    doc_id_prefixes: list[str]
    uri_schemes: list[str]
    max_age_hours: int  # older department maps are not used (§8.4)
    map_uri: str  # gs:// URI of the map the associates indexer writes; {project} = the job's own project


class Environment(BaseModel):
    """What a job's deployment sets (CA_* variables): its own project, endpoints, tokens, backends."""

    project: str  # the GCP project the job runs in and writes to (stage and prod are two projects)
    vertex_project: str  # the judge's project; the job's own project unless CA_VERTEX_PROJECT says otherwise
    run_gate_uri: str | None  # gs://<bucket>/<object> holding {"open_until": ...}; unset = always open
    bq_endpoint: str | None
    gcs_endpoint: str | None
    slack_api: str
    slack_token: str
    github_api: str
    github_token: str
    cloud_run_api: str
    sentry_dsn: str | None
    secrets_backend: str
    judge_backend: str
    code_version: str

    @property
    def emulator(self) -> bool:
        return self.bq_endpoint is not None


class Settings(BaseModel):
    log_project: str  # Gemini Enterprise's log export (analytics), read by stage and prod alike
    evals_project: str  # the evaluator's aiel_evals
    secrets: Secrets
    datasets: Datasets
    log_table: str
    ge_metrics_table: str
    production_engine: str
    evaluator: Evaluator
    canary: Canary
    timing: Timing
    sizes: Sizes
    pace: Pace
    judge: Judge
    metrics: Metrics
    strata: Strata
    alerts: Alerts
    clusters: Clusters
    digest: Digest
    eval_documents: EvalDocuments
    suite: Suite
    github: GitHub
    indexer_jobs: IndexerJobs
    engine_change_methods: list[str]
    content_bucket: str
    data_stores: list[DataStore]
    people_directory: PeopleDirectory
    stage2: Switch = Field(default_factory=Switch)
    evidence_check: Switch = Field(default_factory=Switch)
    leak_audit: LeakAudit
    env: Environment

    def dataset_id(self, dataset: str) -> str:
        """`project.dataset` of a key of Settings.datasets; the emulator holds every dataset in its one project."""
        name = getattr(self.datasets, dataset)
        if dataset in OWN_DATASETS or self.env.emulator:
            return f"{self.env.project}.{name}"
        return f"{self.log_project if dataset == 'log' else self.evals_project}.{name}"

    @property
    def department_map_uri(self) -> str:
        return self.people_directory.map_uri.format(project=self.env.project)

    def table(self, dataset: str, table: str) -> str:
        """Fully qualified table name."""
        return f"{self.dataset_id(dataset)}.{table}"

    def data_store(self, data_store_id: str) -> DataStore | None:
        for ds in self.data_stores:
            if ds.id == data_store_id:
                return ds
        return None

    def bucket_for(self, data_store_id: str) -> str:
        ds = self.data_store(data_store_id)
        return (ds.bucket if ds and ds.bucket else None) or self.content_bucket


def _environment() -> Environment:
    e = os.environ.get
    project = e("CA_PROJECT")
    if not project:
        raise RuntimeError("CA_PROJECT must name the project the job runs in")
    return Environment(
        project=project,
        vertex_project=e("CA_VERTEX_PROJECT") or project,
        run_gate_uri=e("CA_RUN_GATE_URI") or None,
        bq_endpoint=e("CA_BQ_ENDPOINT") or None,
        gcs_endpoint=e("CA_GCS_ENDPOINT") or None,
        slack_api=e("CA_SLACK_API", "https://slack.com/api"),
        slack_token=e("CA_SLACK_TOKEN", ""),
        github_api=e("CA_GITHUB_API", "https://api.github.com"),
        github_token=e("CA_GITHUB_TOKEN", ""),
        cloud_run_api=e("CA_CLOUD_RUN_API", "https://run.googleapis.com"),
        sentry_dsn=e("CA_SENTRY_DSN") or None,
        secrets_backend=e("CA_SECRETS_BACKEND", "gcp"),
        judge_backend=e("CA_JUDGE_BACKEND", "vertex"),
        code_version=e("CA_CODE_VERSION", "dev"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    path = Path(os.environ.get("CA_SETTINGS", REPO_ROOT / "config" / "settings.yaml"))
    raw = yaml.safe_load(path.read_text())
    raw["env"] = _environment()
    return Settings.model_validate(raw)


def now() -> datetime:
    """Current UTC time; CA_NOW pins it for simulated runs on synthetic data."""
    pinned = os.environ.get("CA_NOW")
    if pinned:
        return datetime.fromisoformat(pinned).astimezone(UTC)
    return datetime.now(UTC)
