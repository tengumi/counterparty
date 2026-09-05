FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY packages/contracts packages/contracts
COPY services/mcp/pyproject.toml services/mcp/uv.lock services/mcp/

WORKDIR /app/services/mcp
RUN uv sync --frozen --no-dev --no-install-project

COPY services/mcp/src src
RUN uv sync --frozen --no-dev

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

CMD ["uv", "run", "uvicorn", "counterparty_mcp.app:app", "--host", "0.0.0.0", "--port", "8000"]

