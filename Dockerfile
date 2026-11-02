# One image for every job (§12.3); the job is the `ca` command, e.g. `ca quality-assessor`.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 analyzer
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
COPY config ./config
COPY judge_versions ./judge_versions
COPY suite_cases ./suite_cases
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER analyzer
ENTRYPOINT ["ca"]
