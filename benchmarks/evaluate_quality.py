"""Живые диалоги для ручной оценки пользы: подрядчик, смена оплаты, группа и пробелы."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from benchmarks.evaluate_review import summarize_turn
from counterparty_agent.ai import reasoning, transport
from counterparty_agent.api import runtime
from counterparty_agent.api.routes import create_app
from counterparty_agent.config import Settings
from counterparty_agent.workflow import review

CASE_DIALOGUES = {
    "case_advance": [
        "Я рассматриваю ООО «АПРЕЛЬ» как подрядчика и планирую аванс. "
        "Проверь компанию по ИНН 7813664770. На что обратить внимание?",
        "Какой факт здесь важнее всего для решения об авансе?",
        "Покажи источники для взыскания, выручки и арбитража.",
    ],
    "case_buyer": [
        "ООО «ТЕТРАДОМ» просит поставить товар с оплатой через 60 дней. "
        "Проверь ИНН 9714038662 и объясни, что важно именно для решения об отсрочке.",
        "Отрицательный капитал означает, что компания банкрот?",
        "Меняем оплату: теперь отсрочка 30 дней. Сумма поставки 2 млн рублей. "
        "Что это меняет для нас как продавца?",
    ],
    "case_enforcement": [
        "Мы хотим перечислить существенный аванс ООО ЛПК «САМЗА», ИНН 8622002583. "
        "Назови три главных основания для дополнительной проверки.",
        "Это полная сумма долга компании? Можно ли сложить арбитраж и исполнительные производства?",
    ],
    "case_calm": [
        "Планируем небольшую сделку с ООО «ТЕХПРОФ», ИНН 1684017097, "
        "оплата после выполнения работ. Нужна быстрая проверка без лишней перестраховки.",
        "Рост выручки означает, что компания прибыльна?",
    ],
    "case_missing": [
        "Проверь ООО «ЛЕ МОНЛИД», ИНН 5029069967. Надёжная компания?",
        "Рассматриваем её как поставщика, хотим перечислить аванс. "
        "Какова полная сумма активных производств и можно ли сравнить её с выручкой?",
    ],
    "case_group": [
        "Мы выбираем исполнителя для проекта и рассматриваем ТЕХПРОФ 1684017097, "
        "АПРЕЛЬ 7813664770 и САМЗУ 8622002583. Предполагается аванс. "
        "Сравни их и скажи, кого нужно проверить особенно внимательно до оплаты.",
        "А что по второй компании именно для нашей сделки?",
        "Вернись ко всей группе. Кого ты считаешь победителем сравнения?",
    ],
}


@contextmanager
def measure_calls(calls: list[dict]):  # type: ignore[no-untyped-def]
    """Замерить SDK-вызовы без сообщений, ключей и скрытых рассуждений.

    Время включает сеть и повторы SDK, но не является временем первого токена.
    Подмена ограничена прогоном и восстанавливается даже после ошибки.
    """

    stage: ContextVar[str] = ContextVar("quality_stage", default="route_or_select")
    original_client = transport.create_client
    original_runtime = runtime.create_client
    original_structured = reasoning.structured_call
    original_review = review.structured_call

    async def structured(*values, **options):  # type: ignore[no-untyped-def]
        token = stage.set(values[-1].__name__)
        try:
            return await original_structured(*values, **options)
        finally:
            stage.reset(token)

    def client_factory(settings):  # type: ignore[no-untyped-def]
        client = original_client(settings)

        async def create(**options):  # type: ignore[no-untyped-def]
            started = time.monotonic()
            item = {"stage": stage.get()}
            calls.append(item)
            try:
                result = await client.chat.completions.create(**options)
                usage = result.usage
                detail = getattr(usage, "completion_tokens_details", None)
                reasoning_tokens = getattr(detail, "reasoning_tokens", None)
                if reasoning_tokens is None:
                    reasoning_tokens = getattr(usage, "reasoning_tokens", None)
                item.update(
                    input_tokens=getattr(usage, "prompt_tokens", None),
                    output_tokens=getattr(usage, "completion_tokens", None),
                    reasoning_tokens=reasoning_tokens,
                    finish_reason=result.choices[0].finish_reason if result.choices else None,
                )
                return result
            except BaseException as error:
                item["error"] = type(error).__name__
                item["http_status"] = getattr(error, "status_code", None)
                raise
            finally:
                item["seconds"] = round(time.monotonic() - started, 3)

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=client.close
        )

    transport.create_client = runtime.create_client = client_factory
    reasoning.structured_call = review.structured_call = structured
    try:
        yield
    finally:
        transport.create_client = original_client
        runtime.create_client = original_runtime
        reasoning.structured_call = original_structured
        review.structured_call = original_review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Разрешить вызовы подключённой модели")
    parser.add_argument("--model", help="Модель только для этого прогона; .env не меняется")
    parser.add_argument("--planning", choices=("combined", "legacy"), default="combined")
    parser.add_argument("--reasoning-effort", choices=("low", "high", "max"), default="low")
    parser.add_argument("--limit", type=int, help="Первые N вопросов каждого выбранного диалога")
    parser.add_argument("--summary-only", action="store_true", help="Не печатать тексты ответов")
    parser.add_argument(
        "--output", type=Path, required=True, help="Локальный результат, не для Git"
    )
    parser.add_argument(
        "--dialogue",
        choices=("contractor", "group", "feedback", "cases", *CASE_DIALOGUES, "all"),
        default="all",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Для сетевой проверки нужен --live")
    settings = Settings()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit должен быть положительным")
    settings = settings.model_copy(
        update={
            "llm_model": args.model or settings.llm_model,
            "llm_reasoning_effort": args.reasoning_effort,
            "llm_combined_planning": args.planning == "combined",
        }
    )
    if not settings.llm_configured:
        parser.error("Подключение модели не настроено")
    events: list[str] = []
    rejections: list[str] = []
    generated: list[None] = []
    fallback = reasoning._safe_analysis_fallback
    validate = reasoning.validate_draft
    structured = reasoning.structured_call

    def tracked(*values, **options):  # type: ignore[no-untyped-def]
        draft = fallback(*values, **options)
        if draft is not None:
            events.append("\n\n".join(block.text for block in draft.blocks))
        return draft

    reasoning._safe_analysis_fallback = tracked

    def checked(draft, catalog):  # type: ignore[no-untyped-def]
        try:
            return validate(draft, catalog)
        except ValueError as error:
            rejections.append(str(error))
            raise

    async def observed(*values, **options):  # type: ignore[no-untyped-def]
        result = await structured(*values, **options)
        if isinstance(result, reasoning.ReviewDraft):
            generated.append(None)
        elif isinstance(result, reasoning.GroundingVerdict):
            rejections.extend(result.reasons)
        return result

    reasoning.validate_draft = checked
    reasoning.structured_call = observed
    report: list[dict] = []
    calls: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="counterparty-quality-") as directory:
        configured = settings.model_copy(
            update={"session_db_path": Path(directory) / "sessions.sqlite3"}
        )
        with measure_calls(calls), TestClient(create_app(configured)) as client:
            source = client.app.state.runtime.source
            inns = ("7813664770", "1684017097", "9705152496")
            selected = []
            for inn in (*inns, "9714038662", "8622002583", "5029069967"):
                found = source.find_by_inn(inn)
                if len(found.candidates) != 1:
                    raise RuntimeError("Нужный для контрольного сценария отчёт не найден")
                selected.append(source.get_snapshot(found.candidates[0].snapshot_id))
            dialogues = {
                **CASE_DIALOGUES,
                "feedback": [
                    "Я рассматриваю ООО «АПРЕЛЬ» как подрядчика и планирую аванс. "
                    "Проверь компанию по ИНН 7813664770. На что обратить внимание?",
                    "Но у компании зелёный статус. Разве этого недостаточно?",
                    "ООО «ТЕТРАДОМ» просит поставить товар с оплатой через 60 дней. "
                    "Проверь ИНН 9714038662 и объясни, что важно именно для решения об отсрочке.",
                    "Меняем оплату: теперь отсрочка 30 дней. "
                    "Сумма поставки 2 млн рублей. Что это меняет для нас как продавца?",
                ],
                "contractor": [
                    "Я рассматриваю ООО «АПРЕЛЬ» как подрядчика и планирую аванс. "
                    "Проверь компанию по ИНН 7813664770. На что обратить внимание?",
                    "Это ремонт помещения: сумма 3 млн рублей, аванс 50%, срок 45 дней. "
                    "Что нужно уточнить у подрядчика перед оплатой?",
                    "Теперь без аванса: оплата после выполнения и приёмки работ. "
                    "Остальные условия прежние. Что меняется в твоём выводе?",
                    "Подтверждает ли отчёт опыт ремонта помещений? Если нет, "
                    "скажи прямо, каких подтверждений не хватает. Не задавай новых вопросов.",
                ],
                "group": [
                    "; ".join(inns),
                    "Выбираю поставщика оборудования: 2 млн рублей, аванс 80%, срок 30 дней. "
                    "Сравни контрагентов: какие различия важны и что уточнить до аванса?",
                    "А что по второй компании именно для нашей сделки?",
                    "Вернись ко всей группе. Каких данных не хватает для выбора? "
                    "Продолжи общую проверку, без новых вопросов.",
                ],
            }
            for dialogue, questions in dialogues.items():
                if args.dialogue not in {dialogue, "all"} and not (
                    args.dialogue == "cases" and dialogue in CASE_DIALOGUES
                ):
                    continue
                session = client.post("/api/sessions").json()["session_id"]
                for position, question in enumerate(questions[: args.limit]):
                    events.clear()
                    rejections.clear()
                    generated.clear()
                    calls.clear()
                    started_at = datetime.now(UTC).isoformat()
                    start = time.monotonic()
                    response = client.post(
                        "/api/chat", json={"session_id": session, "question": question}
                    )
                    payload = response.json()
                    item = summarize_turn(
                        f"{dialogue}:{position}",
                        payload,
                        response.status_code,
                        time.monotonic() - start,
                        selected,
                    )
                    item["fallback_considered"] = bool(events)
                    item["used_fallback"] = payload.get("answer") in events
                    item["word_count"] = len(item["answer"].split())
                    item["generation_attempts"] = len(generated)
                    item["model"] = settings.llm_model
                    item["started_at"] = started_at
                    item["planning"] = args.planning
                    item["reasoning_effort"] = settings.llm_reasoning_effort
                    item["max_tokens"] = settings.llm_max_tokens
                    item["review_max_tokens"] = settings.llm_review_max_tokens
                    item["sdk_max_retries"] = settings.llm_max_retries
                    item["reasoning_enabled"] = settings.llm_reasoning_enabled
                    item["review_reasoning_enabled"] = settings.llm_review_reasoning_enabled
                    item["temperature"] = settings.llm_temperature
                    item["llm_calls"] = [dict(call) for call in calls]
                    item["llm_seconds"] = round(sum(call["seconds"] for call in calls), 3)
                    item["rejections"] = summarize_turn(
                        "validation",
                        {"answer": "\n".join(dict.fromkeys(rejections))},
                        200,
                        0,
                        selected,
                    )["answer"]
                    report.append(item)
                    args.output.write_text(
                        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    displayed = {k: v for k, v in item.items() if k not in {"answer", "rejections"}}
                    print(
                        json.dumps(displayed if args.summary_only else item, ensure_ascii=False),
                        flush=True,
                    )


if __name__ == "__main__":
    main()
