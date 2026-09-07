"""Minimal Deep Agents profile for the counterparty product assistant."""

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    register_harness_profile,
)

from ..config import DETERMINISTIC_PROVIDER, AgentSettings

BUILTIN_TOOLS = frozenset(
    {
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "delete",
        "glob",
        "grep",
        "execute",
        "task",
    }
)
"""General-purpose tools that are outside the product assistant's remit."""


def configure_harness_profile(settings: AgentSettings) -> None:
    """Remove the general-purpose surface using Deep Agents' supported profile API."""
    # A model created through ``init_chat_model`` resolves to the configured
    # provider. Our in-process adapter resolves from its class name instead.
    provider = (
        "deterministicchatmodel"
        if settings.model_provider == DETERMINISTIC_PROVIDER
        else settings.model_provider
    )
    register_harness_profile(
        provider,
        HarnessProfile(
            excluded_tools=BUILTIN_TOOLS,
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )
