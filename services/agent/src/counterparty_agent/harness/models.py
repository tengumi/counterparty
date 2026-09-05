"""Model provider selection (AG-01).

LangChain owns provider adapters, so this module only maps configuration onto
one. ``model_provider`` and ``model_id`` come from settings; the default is the
in-process deterministic adapter, which keeps the service buildable and every
test runnable without a model API key. Naming a real provider swaps the adapter
and nothing else in the harness.
"""

from langchain_core.language_models import BaseChatModel

from ..config import DETERMINISTIC_PROVIDER, AgentSettings
from .deterministic import DeterministicChatModel


def create_chat_model(settings: AgentSettings) -> BaseChatModel:
    """Build the chat model named by configuration."""
    if settings.model_provider == DETERMINISTIC_PROVIDER:
        return DeterministicChatModel(model_id=settings.model_id)
    from langchain.chat_models import init_chat_model

    return init_chat_model(
        settings.model_id,
        model_provider=settings.model_provider,
        temperature=settings.model_temperature,
    )
