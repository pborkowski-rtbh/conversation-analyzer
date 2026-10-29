"""Create every dataset, table and view (§12.10); on the emulator also the copies of the tables we only read."""

from __future__ import annotations

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from conversation_analyzer.bq.client import client, execute, fq, retry
from conversation_analyzer.bq.external import EXTERNAL_TABLES
from conversation_analyzer.bq.schema import TABLES, chunk_table, ddl
from conversation_analyzer.bq.views import views
from conversation_analyzer.settings import get_settings


def create_all() -> list[str]:
    s = get_settings()
    created: list[str] = []
    datasets = ["turns", "metrics", "log_views", "doc_index"]
    if s.env.emulator:
        datasets += ["log", "evals"]
    for key in datasets:
        ds_id = f"{s.env.bq_project}.{getattr(s.datasets, key)}"
        try:
            client().get_dataset(ds_id, retry=retry())
        except NotFound:  # the emulator answers an existing dataset with 500, so exists_ok can't be used
            ds = bigquery.Dataset(ds_id)
            ds.location = "EU"
            client().create_dataset(ds, retry=retry())
    tables = list(TABLES)
    if s.env.emulator:
        tables += list(EXTERNAL_TABLES)
        tables += [chunk_table(d.id) for d in s.data_stores if d.has_content]
    for table in tables:
        execute(ddl(table, emulator=s.env.emulator))
        created.append(table.name)
    for name, sql in views().items():
        execute(f"CREATE OR REPLACE VIEW {fq('log_views', name)} AS {sql}")
        created.append(name)
    return created
