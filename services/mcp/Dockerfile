# syntax=docker/dockerfile:1

# Built from the repository root: `docker build -f services/mcp/Dockerfile .`
# The service depends on packages/ by path, so a context narrowed to the service
# directory cannot resolve counterparty-contracts, -domain or -storage at all.
FROM ghcr.io/astral-sh/uv:0.9.18-python3.13-bookworm-slim AS builder

# The virtualenv is built directly at its final runtime path: moving a finished
# environment afterwards invalidates the console scripts inside it.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /workspace/services/mcp

COPY packages/contracts /workspace/packages/contracts
COPY packages/domain /workspace/packages/domain
COPY packages/storage /workspace/packages/storage
COPY services/mcp/pyproject.toml services/mcp/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY services/mcp/src ./src
# The workspace packages are pinned at 0.1.0 and never bump per change, so uv
# would keep an already installed copy and the image would ship stale contracts.
# Reinstalling them by name is what makes the build reflect the sources copied
# above; --no-editable is required because the runtime stage carries no sources.
RUN uv sync --frozen --no-dev --no-editable \
      --reinstall-package counterparty-contracts \
      --reinstall-package counterparty-domain \
      --reinstall-package counterparty-storage

FROM python:3.13-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN addgroup --system app && adduser --system --ingroup app app
WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv ./.venv

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

CMD ["uvicorn", "counterparty_mcp.app:app", "--host", "0.0.0.0", "--port", "8000"]
