"""Model provider selection (AG-01).

LangChain owns provider adapters, so this module only maps configuration onto
one. ``model_provider`` and ``model_id`` come from settings; the default is the
in-process deterministic adapter, which keeps the service buildable and every
test runnable without a model API key. Naming a real provider swaps the adapter
and nothing else in the harness.
"""

from typing import TypedDict

from langchain_core.language_models import BaseChatModel

from ..config import DETERMINISTIC_PROVIDER, AgentSettings
from .deterministic import DeterministicChatModel


class _ConnectionOptions(TypedDict, total=False):
    """Optional provider arguments passed through LangChain."""

    base_url: str
    api_key: str
    max_tokens: int


def create_chat_model(settings: AgentSettings, *, model_id: str | None = None) -> BaseChatModel:
    """Build the chat model named by configuration.

    ``model_id`` overrides the configured id for a specific call site (the
    report summary uses a lighter model); the provider and connection stay.
    """
    chosen = model_id or settings.model_id
    if settings.model_provider == DETERMINISTIC_PROVIDER:
        return DeterministicChatModel(model_id=chosen)
    from langchain.chat_models import init_chat_model

    options: _ConnectionOptions = {}
    if settings.model_base_url:
        options["base_url"] = settings.model_base_url
    if settings.model_api_key:
        options["api_key"] = settings.model_api_key.get_secret_value()
    if settings.model_max_tokens is not None:
        options["max_tokens"] = settings.model_max_tokens
    return init_chat_model(
        chosen,
        model_provider=settings.model_provider,
        temperature=settings.model_temperature,
        **options,
    )
