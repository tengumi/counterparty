"""The product agent exposes no general-purpose Deep Agents tools."""

from typing import Any

from counterparty_agent.config import AgentSettings
from counterparty_agent.harness import profile


def test_product_profile_removes_general_purpose_tools(monkeypatch: Any) -> None:
    """Framework configuration disables files, shell and the default subagent."""
    registered: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        profile,
        "register_harness_profile",
        lambda provider, value: registered.append((provider, value)),
    )

    profile.configure_harness_profile(AgentSettings(model_provider="openai"))

    provider, value = registered[0]
    assert provider == "openai"
    assert {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
        "execute",
        "task",
    } <= value.excluded_tools
    assert value.general_purpose_subagent.enabled is False
