# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.9.18-python3.13-bookworm-slim AS builder

# The virtualenv is built at its final runtime path so console scripts stay valid.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /workspace/services/agent

COPY packages/contracts /workspace/packages/contracts
COPY packages/storage /workspace/packages/storage
COPY services/agent/pyproject.toml services/agent/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY services/agent/src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.13-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv ./.venv

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

CMD ["uvicorn", "counterparty_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
