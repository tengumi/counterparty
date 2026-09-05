"""FastAPI composition root for the UI backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage process-local resources owned by the service."""
    app.state.ready = True
    try:
        yield
    finally:
        app.state.ready = False


def create_app() -> FastAPI:
    """Build the UI API application and register its public routes."""
    application = FastAPI(
        title="Counterparty UI API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(health_router)
    return application


app = create_app()
