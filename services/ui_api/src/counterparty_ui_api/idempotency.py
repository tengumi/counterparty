"""Making a repeated create harmless.

The guarantee is not implemented here. It is the primary key of
``workspace.idempotency_keys``: the same ``(tenant, scope, client_request_id)``
cannot be inserted twice, so two copies of one request race for one row and
exactly one of them wins. This module only decides what each of the three
answers means to an HTTP caller:

* the id is new — the caller does the work and completes the reservation in the
  same transaction as the write, so a completed reservation can never name a
  resource that was rolled back;
* the id finished earlier with the same payload — the first resource is
  returned again, and nothing is created;
* the id is still in flight — the caller is told so instead of racing it, and
  may retry;
* the id was used for a *different* payload — the request is refused, because
  replaying the first resource would silently discard this request.

The reservation is committed before the work starts. That is what makes the
in-flight answer possible at all, and it is why a failed attempt releases its
reservation explicitly after rolling back. A process crash leaves an in-flight
key until worker state can be reconciled: age alone cannot prove that the
original writer stopped. Automatic takeover needs fencing or reconciliation
before it can safely prevent duplicate projects.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from counterparty_contracts import ErrorCode
from counterparty_storage import AsyncUnitOfWork
from counterparty_storage.repositories import Reservation, ReservationOutcome

from .errors import ApiError

__all__ = ["fingerprint_of", "release_reservation", "reserve_or_answer"]


def fingerprint_of(payload: Mapping[str, Any]) -> str:
    """Return the digest of a canonical rendering of the request payload.

    The digest is what distinguishes "the same request again" from "a different
    request under a recycled id". It covers the acting user as well, so one
    tenant's two users cannot silently share a reservation.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def reserve_or_answer(
    uow: AsyncUnitOfWork,
    *,
    scope: str,
    client_request_id: UUID,
    fingerprint: str,
    resource_kind: str,
) -> Reservation:
    """Claim the request id, or refuse in the way its state calls for.

    A new reservation is committed before returning, so a concurrent copy of
    the same request sees it instead of starting a second one.

    Args:
        uow: Transaction of the request.
        scope: Operation the id was issued for, e.g. ``projects.create``.
        client_request_id: The caller's request id.
        fingerprint: Digest of this request's payload.
        resource_kind: What the operation creates.

    Returns:
        The reservation, either freshly started or already completed.

    Raises:
        ApiError: If an identical request is still running (``conflict``,
            retryable), or if the id was already used for a different payload
            (``conflict``, not retryable).
    """
    reservation = await uow.idempotency.reserve(
        scope=scope,
        client_request_id=client_request_id,
        request_fingerprint=fingerprint,
        resource_kind=resource_kind,
        stale_after=None,  # A slow writer must retain exclusive ownership of its request id.
    )
    if reservation.outcome is ReservationOutcome.IN_FLIGHT:
        await uow.rollback()
        raise ApiError(
            ErrorCode.CONFLICT,
            "an identical request is still being processed; retry to read its result",
            retryable=True,
            details={"reason": "request_in_flight", "client_request_id": str(client_request_id)},
        )
    if reservation.outcome is ReservationOutcome.STARTED:
        await uow.commit()
    return reservation


async def release_reservation(uow: AsyncUnitOfWork, *, scope: str, client_request_id: UUID) -> None:
    """Give the request id back after the work behind it failed.

    Without this a failed attempt would hold its id forever and the caller's
    retry — the very thing an idempotent create exists for — would be refused.
    A completed key survives cleanup, including an ambiguous commit result.
    """
    await uow.rollback()
    await uow.idempotency.release(scope=scope, client_request_id=client_request_id)
    await uow.commit()
