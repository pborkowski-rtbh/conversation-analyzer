# Local development and tests. Everything runs against the docker compose stack (BigQuery emulator, fake GCS,
# stubs for Slack, GitHub and Cloud Run); the only paid target is suite-live.
SHELL := /bin/bash
COMPOSE ?= $(if $(shell command -v docker-compose),docker-compose,docker compose)
UV ?= uv
IMAGE ?= conversation-analyzer:local
ENV := set -a && . ./local.env && set +a &&
CA := $(ENV) $(UV) run ca

DAY ?=
WEEK ?=
PASSES ?= 3
PART ?= all
LIMIT ?= 0
JUDGE_VERSION ?=
SUITE_ARGS = --part $(PART) --limit $(LIMIT) $(if $(JUDGE_VERSION),--judge-version $(JUDGE_VERSION))
REPORTS ?=
DATA_STORE ?=
SINCE ?=
CODE_VERSION ?= $(shell git rev-parse HEAD 2>/dev/null || echo dev)

.DEFAULT_GOAL := help

.PHONY: help
help: ## List the targets
	@grep -hE '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- stack -------------------------------------------------------------------------------------------------------

.PHONY: install
install: ## Install dependencies with uv
	$(UV) sync

.PHONY: up
up: ## Start the emulator, fake GCS and the stubs, then create all tables
	$(COMPOSE) up -d --build
	@for i in $$(seq 1 30); do nc -z localhost 9050 && break; sleep 1; done
	$(MAKE) db-init

.PHONY: down
down: ## Stop the stack (the emulator keeps nothing)
	$(COMPOSE) down

.PHONY: db-init
db-init: ## Create every dataset, table and view on the emulator
	$(CA) db-init

.PHONY: db-reset
db-reset: ## Empty the emulator (restart; dropping tables corrupts it) and create everything again
	$(COMPOSE) restart bigquery gcs
	@for i in $$(seq 1 30); do nc -z localhost 9050 && break; sleep 1; done
	$(MAKE) db-init

.PHONY: db-check
db-check: ## Compare the emulator's tables, columns, partitioning and views with bq/schema.py
	$(CA) db-init --check

.PHONY: leak-audit
leak-audit: ## Read stored rows back through the leak guard: make leak-audit SINCE=YYYY-MM-DD (default 7 days ago)
	$(CA) leak-audit --since $(or $(SINCE),$$(date -u -v-7d +%F 2>/dev/null || date -u -d '7 days ago' +%F))

.PHONY: seed
seed: ## Write the synthetic scenario (log rows, documents, chunks) into the emulator
	$(CA) dev-seed

# --- jobs --------------------------------------------------------------------------------------------------------

.PHONY: run-assessor
run-assessor: ## Run quality-assessor once against the emulator (fake judge)
	$(CA) quality-assessor

.PHONY: run-monitor
run-monitor: ## Run quality-monitor once (alerts go to the Slack stub)
	$(CA) quality-monitor

.PHONY: run-daily
run-daily: ## Run quality-daily (DAY=YYYY-MM-DD, default yesterday)
	$(CA) quality-daily $(if $(DAY),--day $(DAY))

.PHONY: run-weekly
run-weekly: ## Run quality-weekly (WEEK=<monday>, default last week)
	$(CA) quality-weekly $(if $(WEEK),--week $(WEEK))

.PHONY: record
record: ## Record a change event: make record KIND=DOCUMENT DOC_ID=.. DATA_STORE=.. [DAY=..] [CLUSTER=..]
	$(CA) quality-record --kind $(KIND) $(if $(DAY),--day $(DAY)) $(if $(HOUR),--hour $(HOUR)) \
		$(if $(DOC_ID),--doc-id $(DOC_ID)) $(if $(DATA_STORE),--data-store $(DATA_STORE)) \
		$(foreach c,$(CLUSTER),--cluster $(c))

.PHONY: alert-lookup
alert-lookup: ## Show the sessions behind an alert: make alert-lookup ALERT=alert-...
	$(CA) quality-alert-lookup --alert $(ALERT)

.PHONY: demo
demo: db-reset seed run-assessor run-monitor ## Whole pipeline on the synthetic scenario (seeded today)
	$(CA) quality-daily --day $$(date -u +%F)
	$(CA) quality-weekly --week $$(date -u +%F)
	@curl -s localhost:8088/_test/state | python3 -c 'import json,sys; [print(m["channel"], m["text"], sep="\n", end="\n\n") for m in json.load(sys.stdin)["messages"]]'


# --- local Grafana (proposed dashboard, §8.8) -----------------------------------------------------------------------

DASHBOARD ?= docker/grafana/dashboards/bolek-quality.json

.PHONY: grafana
grafana: ## Local Grafana on :3000 over the emulator, with mocked metrics and the dashboard (resets the emulator)
	$(COMPOSE) --profile grafana up -d --build
	@for i in $$(seq 1 30); do nc -z localhost 9050 && break; sleep 1; done
	$(MAKE) db-reset grafana-seed
	@for i in $$(seq 1 60); do curl -sf localhost:3000/api/health >/dev/null && break; sleep 1; done
	$(MAKE) grafana-load

.PHONY: grafana-seed
grafana-seed: ## Write eight weeks of mocked metrics rows (the metrics tables must be empty: make db-reset first)
	$(CA) dev-seed-dashboard
	-$(COMPOSE) --profile grafana restart gcp-proxy  # empties the proxy's query cache

.PHONY: grafana-load
grafana-load: ## Load the dashboard file into the local Grafana and warm the query cache (DASHBOARD=path)
	$(UV) run python docker/grafana/sync.py load $(DASHBOARD)

.PHONY: grafana-save
grafana-save: ## Write the local Grafana's version of the dashboard (edited in the UI) back into the file
	$(UV) run python docker/grafana/sync.py save $(DASHBOARD)

.PHONY: dashboard-check
dashboard-check: ## Every panel's SQL of DASHBOARD on the emulator: errors and empty panels fail (after make grafana-seed)
	$(CA) dashboard-check $(DASHBOARD) $(foreach v,$(VARS),--var $(v)) $(if $(ALLOW_EMPTY),--allow-empty)

.PHONY: grafana-down
grafana-down: ## Stop the local Grafana and its proxy
	$(COMPOSE) --profile grafana stop grafana gcp-proxy

# --- judge test suite ----------------------------------------------------------------------------------------------

.PHONY: suite-coverage
suite-coverage: ## Check the suite cases against every scenario minimum of §11.1
	$(CA) quality-judge-suite --check

.PHONY: suite
suite: ## Run the suite with the fake judge (checks the runner, costs nothing); PART, LIMIT, JUDGE_VERSION
	$(CA) quality-judge-suite --passes 1 $(SUITE_ARGS)

.PHONY: suite-restore
suite-restore: ## Load stored suite runs back into the emulator after a reset (REPORTS=..., default every full run)
	$(CA) dev-load-suite-runs $(REPORTS)

.PHONY: suite-live
suite-live: ## PAID: the suite on Vertex (eu); PASSES, PART, LIMIT, JUDGE_VERSION; log the spend in plan.md
	@read -p "This calls paid Vertex models. Continue? [y/N] " ok && [ "$$ok" = y ]
	$(ENV) CA_JUDGE_BACKEND=vertex $(UV) run ca quality-judge-suite --passes $(PASSES) $(SUITE_ARGS)

# --- quality -----------------------------------------------------------------------------------------------------

.PHONY: test
test: db-reset ## All tests on a fresh emulator (needs make up); paid live tests are excluded
	$(UV) run pytest -q -p no:logging --no-cov

.PHONY: test-unit
test-unit: ## Tests that need no docker stack
	$(UV) run pytest -q -p no:logging --no-cov -m 'not emulator and not live'

.PHONY: coverage
coverage: db-reset ## All tests with branch coverage on a fresh emulator; fails under 90 %
	$(UV) run pytest -q -p no:logging --cov --cov-report=term-missing

.PHONY: lint
lint: ## ruff check + format check
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests

.PHONY: fmt
fmt: ## ruff fix + format
	$(UV) run ruff check --fix src tests
	$(UV) run ruff format src tests

.PHONY: build
build: ## Build the job image; run records name the git SHA it was built from (CA_CODE_VERSION)
	docker build --build-arg CODE_VERSION=$(CODE_VERSION) -t $(IMAGE) .
