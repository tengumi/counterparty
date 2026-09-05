# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.9.18 AS uv

FROM python:3.13-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv

# The virtualenv is built at its final runtime path so console scripts stay valid.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /workspace/services/ui_api
COPY packages/contracts /workspace/packages/contracts
COPY services/ui_api/pyproject.toml services/ui_api/uv.lock ./
COPY services/ui_api/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv ./.venv

USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
CMD ["uvicorn", "counterparty_ui_api.app:app", "--host", "0.0.0.0", "--port", "8000"]

