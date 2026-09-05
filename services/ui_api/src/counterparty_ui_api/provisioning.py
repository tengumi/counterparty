"""Making the configured demo identities exist in the workspace.

A session carries a tenant and a user, and every project row references both.
The demo identities are configured on the server, so the rows they name are
created by the server too — otherwise the first sign-in would produce a session
that cannot own anything.

This writes only ``workspace`` and only the identity rows named by the
configuration. It creates no project, no chat and no report: a demo identity is
an empty account, not a pre-filled one. It is also idempotent, so restarting
the process does not duplicate anyone.
"""

from uuid import UUID

from counterparty_storage.workspace.models import Membership, Tenant, User
from sqlalchemy.dialects.postgresql import insert

from .config import Settings
from .database import SessionFactory

__all__ = ["ensure_demo_identities"]


async def ensure_demo_identities(factory: SessionFactory, settings: Settings) -> None:
    """Create the tenant, user and membership row of each demo login.

    Args:
        factory: Session factory of this process.
        settings: The server-side configuration naming the demo identities.
    """
    if not settings.demo_users:
        return
    async with factory() as session:
        for login, identity in settings.demo_users.items():
            tenant_id = UUID(str(identity.tenant_id))
            user_id = UUID(str(identity.user_id))
            await session.execute(
                insert(Tenant)
                .values(id=tenant_id, slug=login, title=identity.display_name)
                .on_conflict_do_nothing()
            )
            await session.execute(
                insert(User)
                .values(
                    id=user_id,
                    email=f"{login}@demo.invalid",
                    display_name=identity.display_name,
                )
                .on_conflict_do_nothing()
            )
            await session.execute(
                insert(Membership)
                .values(tenant_id=tenant_id, user_id=user_id)
                .on_conflict_do_nothing()
            )
        await session.commit()
