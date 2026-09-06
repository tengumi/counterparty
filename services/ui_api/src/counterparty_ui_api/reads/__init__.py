"""Read models and DTO mapping behind the responses.

The read side of the service: turning stored rows into the public contract
DTOs (:mod:`.views`) and the batched project/company read models
(:mod:`.models`). Nothing here writes.
"""

from .models import (
    CompanyPage,
    ProjectDetails,
    load_company_page,
    load_project_details,
)
from .views import (
    as_analysis_artifact,
    as_page,
    as_project,
    as_thread_conversation,
    as_user_decision,
)

__all__ = [
    "CompanyPage",
    "ProjectDetails",
    "as_analysis_artifact",
    "as_page",
    "as_project",
    "as_thread_conversation",
    "as_user_decision",
    "load_company_page",
    "load_project_details",
]
