"""Every HTTP router of the UI backend, gathered for the composition root."""

from .auth import router as auth_router
from .companies import directory_router as company_directory_router
from .companies import router as project_companies_router
from .conversation import router as conversation_router
from .decisions import router as decisions_router
from .health import router as health_router
from .projects import router as projects_router
from .report_details import router as report_details_router
from .reports import router as reports_router

__all__ = [
    "auth_router",
    "company_directory_router",
    "conversation_router",
    "decisions_router",
    "health_router",
    "project_companies_router",
    "projects_router",
    "report_details_router",
    "reports_router",
]
