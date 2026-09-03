"""Модульные тесты адаптера DSLab без API-ключа и сетевых запросов."""

import asyncio
from types import SimpleNamespace
from typing import Any

from counterparty_agent.llm import build_messages, generate_answer


class _FakeCompletions:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(
            model="qwen3.7-plus",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="Данных недостаточно."),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=25, completion_tokens=4),
        )


def test_build_messages_separates_data_from_rules() -> None:
    messages = build_messages(
        "Какие риски?",
        {"company": "Демо", "evidence_id": "status"},
        [("user", "Продолжим"), ("assistant", "Да")],
    )

    assert messages[0]["role"] == "system"
    assert "<INPUT_DATA>" in messages[-1]["content"]
    assert '"evidence_id":"status"' in messages[-1]["content"]
    assert "<QUESTION>\nКакие риски?" in messages[-1]["content"]


def test_generate_answer_uses_confirmed_dslab_parameters() -> None:
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = SimpleNamespace(
        llm_model="qwen3.7-plus",
        llm_temperature=0.1,
        llm_max_tokens=1200,
        llm_reasoning_enabled=False,
    )

    result = asyncio.run(
        generate_answer(settings, "Что известно?", {"status": "ACTIVE"}, client=client)
    )

    assert result.answer == "Данных недостаточно."
    assert completions.kwargs["model"] == "qwen3.7-plus"
    assert completions.kwargs["extra_body"] == {"reasoning": {"enabled": False}}
