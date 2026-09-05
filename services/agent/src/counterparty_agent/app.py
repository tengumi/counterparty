"""FastAPI application factory for the agent service."""

from typing import Annotated

from fastapi import FastAPI
from pydantic import BaseModel

from .composition import CheckpointerFactory, create_lifespan
from .config import AgentSettings
from .transport import create_transport_router


class HealthResponse(BaseModel):
    """Liveness response without external dependency probing."""

    status: str
    service: str
    checkpoint_backend: str


def create_app(
    settings: AgentSettings | None = None,
    *,
    checkpointer_factory: CheckpointerFactory | None = None,
) -> FastAPI:
    """Create an app without opening network or database resources at import time."""
    resolved_settings = settings or AgentSettings()
    lifespan = (
        create_lifespan(resolved_settings)
        if checkpointer_factory is None
        else create_lifespan(resolved_settings, checkpointer_factory)
    )
    app = FastAPI(title="Counterparty Agent", version="0.1.0", lifespan=lifespan)
    app.include_router(create_transport_router())

    @app.get("/healthz", response_model=HealthResponse)
    async def health() -> Annotated[HealthResponse, "Liveness only"]:
        backend = "postgres" if resolved_settings.postgres_dsn is not None else "not_configured"
        return HealthResponse(
            status="ok",
            service=resolved_settings.service_name,
            checkpoint_backend=backend,
        )

    return app


app = create_app()
