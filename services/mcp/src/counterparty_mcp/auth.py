"""Opaque server-to-server credential verification through FastMCP auth."""

import hashlib
import hmac

from fastmcp.server.auth import AccessToken, TokenVerifier


class ServiceTokenVerifier(TokenVerifier):
    """Accept one provisioned agent credential, retaining only its SHA256 digest.

    This is an internal service identity, not user OAuth. Rotation replaces the
    process configuration; public or per-user access is outside this service.
    HTTP authentication, Bearer parsing and scope enforcement belong to FastMCP.
    """

    def __init__(self, expected_sha256: str | None) -> None:
        """Configure a required reports scope and optional provisioned digest."""
        super().__init__(required_scopes=["reports:read"])
        self._expected_sha256 = expected_sha256

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify in constant time; an unconfigured service accepts no token."""
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if self._expected_sha256 is None or not hmac.compare_digest(digest, self._expected_sha256):
            return None
        return AccessToken(token=token, client_id="counterparty-agent", scopes=["reports:read"])
