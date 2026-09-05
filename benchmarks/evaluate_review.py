"""Явный платный прогон текущей модели на реальных отчётах, без записи исходных данных."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from counterparty_agent.api.routes import create_app
from counterparty_agent.config import Settings
from counterparty_agent.models import CounterpartySnapshot


def summarize_turn(
    label: str,
    payload: dict,
    status_code: int,
    seconds: float,
    selected: Sequence[CounterpartySnapshot],
) -> dict:
    """Оставляет ответ для ручной оценки; не копирует исходные отчёты и реквизиты."""
    review = payload.get("review") or {}
    answer = payload.get("answer", str(payload.get("detail", "")))
    for i, snapshot in enumerate(selected, 1):
        for name in sorted(
            {snapshot.identity.full_name, snapshot.identity.short_name},
            key=len,
            reverse=True,
        ):
            if name:
                answer = answer.replace(name, f"Компания {i}")
    answer = re.sub(r"\b\d{10,15}\b", "[реквизит]", answer)
    claims = payload.get("answer_claims", payload.get("claims", []))
    cards = payload.get("cards") or ([payload["card"]] if payload.get("card") else [])
    evidence = [*payload.get("evidence", []), *(e for c in cards for e in c["evidence"])]
    available = {e["evidence_id"] for e in evidence}
    cited = {e for claim in claims for e in claim["evidence_ids"]}
    return {
        "scenario": label,
        "http": status_code,
        "status": payload.get("status"),
        "seconds": round(seconds, 2),
        "answer": answer,
        "claim_count": len(claims),
        "evidence_valid": bool(claims)
        and all(c["evidence_ids"] for c in claims)
        and cited <= available,
        "steps": review.get("steps", []),
        "purpose_known": bool(review.get("goal")),
        "advance": review.get("advance"),
        "revision": review.get("context_revision"),
        "focused": payload.get("focus_snapshot_id") is not None,
        "group_size": len(cards),
        "document_sources": sum(e.get("quality") == "user_document" for e in evidence),
    }


def enable_safe_trace(drafts: list[dict]) -> None:
    """Печатает только тип шага и результат валидации, без фактов и запросов."""
    from counterparty_agent.ai import reasoning, transport

    original = transport._request_completion

    async def traced(*args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            result = await original(*args, **kwargs)
        except Exception as error:
            print({"call_error": type(error).__name__}, flush=True)
            raise
        try:
            value = json.loads(result.answer)
            if "blocks" in value or "unsupported_blocks" in value:
                # Только выход модели для локального ручного разбора: не запросы,
                # не настройки подключения и не исходные snapshots.
                drafts.append(value)
            print(
                {
                    key: value[key]
                    for key in (
                        "action",
                        "scope",
                        "position",
                        "answer_mode",
                        "topics",
                        "unsupported_blocks",
                        "answers_question",
                    )
                    if key in value
                }
                or {"blocks": len(value.get("blocks", []))},
                flush=True,
            )
        except (ValueError, TypeError):
            print({"json": "invalid"}, flush=True)
        return result

    transport._request_completion = traced
    reasoning._request_completion = traced
    original_validation = reasoning.validate_draft

    def validate(*args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return original_validation(*args, **kwargs)
        except ValueError as error:
            print({"validation": str(error)}, flush=True)
            raise

    reasoning.validate_draft = validate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Разрешить вызовы настроенной модели")
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Показать метаданные шагов; сохранить черновики модели в локальный JSON",
    )
    parser.add_argument("--max-turns", type=int, help="Ограничить основной диалог для диагностики")
    parser.add_argument(
        "--inn",
        action="append",
        default=[],
        help="ИНН участника; повторить для каждого кандидата",
    )
    parser.add_argument(
        "--suite",
        choices=("core", "project", "all"),
        default="all",
        help="Основной диалог, документ с отчётами либо оба сценария",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Локальный JSON с обезличенным результатом"
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Вызовы API требуют явного --live")
    if args.max_turns is not None and args.max_turns < 2:
        parser.error("Нужно не менее двух шагов: выбор и аналитический вопрос")
    drafts: list[dict] = []
    if args.trace:
        enable_safe_trace(drafts)
    settings = Settings()
    if not settings.llm_configured:
        parser.error("Модель не настроена")
    report: dict[str, object] = {
        "at": datetime.now(UTC).isoformat(),
        "model": settings.llm_model,
        "review_reasoning": settings.llm_review_reasoning_enabled,
        "review_max_tokens": settings.llm_review_max_tokens,
        "reasoning_max_tokens": settings.llm_reasoning_max_tokens,
        "source": "Настроенный локальный JSON; исходные данные не записываются",
        "note": "Условия сделки — сценарий проверки, а не независимые факты отчётов.",
        "turns": [],
    }
    turns: list[dict[str, object]] = []

    def save() -> None:
        report["turns"] = turns
        if args.trace:
            report["model_output_diagnostics"] = drafts
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="counterparty-live-eval-") as directory:
        configured = settings.model_copy(
            update={"session_db_path": Path(directory) / "sessions.sqlite3"}
        )
        with TestClient(create_app(configured)) as client:
            source = client.app.state.runtime.source
            selected = []
            if args.inn:
                for inn in args.inn:
                    matches = [s for s in source.snapshots if s.identity.inn == inn]
                    if len(matches) != 1:
                        raise RuntimeError("Участник сценария не найден однозначно")
                    selected.append(matches[0])
            else:
                for color in ("GREEN", "YELLOW", "RED"):
                    candidate = next(
                        (s for s in source.snapshots if s.bank_risk.raw_level == color), None
                    )
                    if candidate:
                        selected.append(candidate)
            if len(selected) < 2:
                raise RuntimeError("Для сценария нужны минимум два доступных отчёта")
            session = client.post("/api/sessions").json()["session_id"]
            questions = [
                ("selection", "; ".join(s.identity.inn for s in selected)),
                (
                    "advance",
                    "Выбираю поставщика оборудования. Сумма сделки 2 млн рублей, "
                    "аванс 80%, срок поставки 30 дней. "
                    "Сравни риски и скажи что проверить перед оплатой.",
                ),
                (
                    "postpayment",
                    "Меняем условия: оплата после поставки и приёмки, без аванса. "
                    "Как изменится твой вывод по этим поставщикам?",
                ),
                (
                    "focused",
                    "А что по второй компании: на что обратить внимание при этих условиях?",
                ),
                (
                    "gaps",
                    "Каких данных не хватает, чтобы сделать обоснованный выбор? Не задавай "
                    "новых вопросов об условиях, нужна общая проверка доступных отчётов.",
                ),
            ]
            if args.suite == "project":
                questions = questions[:3]
            if args.max_turns is not None:
                questions = questions[: args.max_turns]
            for label, question in questions:
                started = time.monotonic()
                response = client.post(
                    "/api/chat", json={"session_id": session, "question": question}
                )
                payload = response.json()
                turn = summarize_turn(
                    label,
                    payload,
                    response.status_code,
                    time.monotonic() - started,
                    selected,
                )
                turns.append(turn)
                save()
                print(
                    json.dumps(
                        {
                            key: turn[key]
                            for key in ("scenario", "http", "status", "seconds", "claim_count")
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            if args.suite in {"project", "all"}:
                created = client.post(
                    "/api/projects",
                    json={
                        "session_id": session,
                        "title": "Проверка условий поставки",
                        "goal": "",
                    },
                )
                created.raise_for_status()
                project = created.json()
                # Это явно предложенные условия демо, а не новые сведения о компаниях.
                document = (
                    "Проект условий поставки оборудования, не подписан.\n"
                    "Сумма договора: 2 млн рублей. Пункт 4: аванс 80% до отгрузки.\n"
                    "Поставка в течение 30 дней. Порядок приёмки согласуется отдельно.\n"
                    "Документ не подтверждает финансовые показатели или статус поставщика."
                )
                uploaded = client.post(
                    f"/api/projects/{project['project_id']}/documents",
                    params={"expected_revision": project["revision"], "name": "условия.txt"},
                    content=document.encode(),
                )
                uploaded.raise_for_status()
                project = uploaded.json()
                for label, question in [
                    (
                        "document_conflict",
                        "Сопоставь условия проекта договора с нашей "
                        "постоплатой и отчётами компаний. Где есть расхождения и что проверить "
                        "до подписания? Согласованные условия пока не меняем.",
                    ),
                    (
                        "document_revision",
                        "Согласовали изменение договора: оплата после "
                        "поставки и приёмки, без аванса. Что ещё осталось проверить по отчётам "
                        "и какие условия документа нужно исправить?",
                    ),
                ]:
                    started = time.monotonic()
                    response = client.post(
                        f"/api/projects/{project['project_id']}/ask",
                        json={
                            "expected_revision": project["revision"],
                            "question": question,
                        },
                    )
                    payload = response.json()
                    turn = summarize_turn(
                        label,
                        payload,
                        response.status_code,
                        time.monotonic() - started,
                        selected,
                    )
                    turns.append(turn)
                    save()
                    if payload.get("project"):
                        project = payload["project"]
                    print(
                        {
                            key: turn[key]
                            for key in (
                                "scenario",
                                "http",
                                "status",
                                "seconds",
                                "claim_count",
                                "evidence_valid",
                                "document_sources",
                            )
                        },
                        flush=True,
                    )
    save()
    print(f"Результат: {args.output}")


if __name__ == "__main__":
    main()
