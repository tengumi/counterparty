"""Server-side settings are read from the environment, never from a request."""

import pytest

from counterparty_ui_api.config import DEMO_USERS_ENV, Settings


def test_defaults_provision_two_tenants() -> None:
    """The built-in demo identities live in two tenants, so isolation shows."""
    settings = Settings.from_env({})

    tenants = {user.tenant_id for user in settings.demo_users.values()}
    assert len(settings.demo_users) == len(tenants) == 2
    assert settings.session_cookie_secure is True


def test_demo_users_can_be_replaced_from_the_environment() -> None:
    """A deployment provisions its own identities without a code change."""
    settings = Settings.from_env(
        {
            DEMO_USERS_ENV: (
                '{"only-one": {"tenant_id": "00000000-0000-4000-8000-0000000000e9",'
                ' "user_id": "00000000-0000-4000-8000-0000000000a9",'
                ' "display_name": "Единственный"}}'
            )
        }
    )

    assert list(settings.demo_users) == ["only-one"]
    assert settings.demo_tenant_of("demo-analyst") is None


def test_malformed_demo_users_fail_loudly() -> None:
    """A broken configuration stops the process instead of silently allowing all."""
    with pytest.raises(ValueError):
        Settings.from_env({DEMO_USERS_ENV: "not json"})


def test_demo_auth_can_be_disabled_by_flag() -> None:
    """The demo sign-in is switched off without editing the code."""
    assert Settings.from_env({"UI_API_DEMO_AUTH": "false"}).demo_auth_enabled is False
