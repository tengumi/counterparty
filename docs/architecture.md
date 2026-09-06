# Архитектура Counterparty Workspace

**Статус:** принято для MVP
**Версия:** 1.1 · 5 сентября 2026

Подробное архитектурное ТЗ находится в
[`Specs/01_ARCHITECTURE.md`](Specs/01_ARCHITECTURE.md), контракты — в
[`Specs/10_SYSTEM_CONTRACTS.md`](Specs/10_SYSTEM_CONTRACTS.md), порядок
реализации — в [`WORK_PLAN.md`](WORK_PLAN.md). Этот файл намеренно остаётся
коротким, чтобы не создавать вторую расходящуюся архитектуру.

## Границы системы

```text
Browser
  └─ apps/web
       ├─ REST /api/v1 ───────► services/ui_api
       └─ RPC /rpc/agent ─────► services/agent
                                  ├─ model provider
                                  ├─ project-scoped document tools
                                  └─ MCP tools ─► services/mcp

services/ui_api ───────────────► PostgreSQL: reports + workspace
services/mcp ──────────────────► PostgreSQL: reports, read-only
services/agent ────────────────► PostgreSQL: workspace + checkpoints
scripts/import_reports ────────► PostgreSQL: reports
```

Развёртываемых частей четыре: web, UI Backend, Agent Service и внутренний MCP.
Каждая имеет собственный `Dockerfile`. Скрипт импорта, shared-пакеты, миграции
и обработчики документов не являются дополнительными сервисами. Общий Compose
добавляется после независимого запуска сервисов.

## Общие пакеты

- `packages/contracts` — Pydantic DTO, enums, identifiers и публичные схемы;
- `packages/domain` — чистые вычисления, правила, evidence и сравнение;
- `packages/storage` — ORM mapping, repositories и unit of work.

Общий пакет не открывает сеть и не запускает миграции при импорте. Сервис
подключает инфраструктуру только в собственном composition root.

## Данные и доверие

PostgreSQL содержит две области: неизменяемые снимки и нормализованные отчёты в
`reports`, проектное состояние и память в `workspace`. Агент читает отчёты через
ограниченный MCP, а UI Backend использует те же domain-функции поверх
репозиториев. Полный snapshot не передаётся модели и не сохраняется в
checkpoint.

JSON из дизайнерского набора является разрешённым mock-источником. Скрипт
`scripts/import_reports` загружает его идемпотентно, сохраняя provenance,
неизвестные значения и различие между отсутствующим полем и нулём.

## Агент и UI

Агентный runtime использует LangGraph/Deep Agents и штатные механизмы
assistant-stream. Детерминированные вычисления остаются в domain-коде. Модель
может выбирать разрешённые инструменты и формулировать ответ, но не создаёт
факты и не записывает решение пользователя.

React-интерфейс реализует принятый дизайнерский HTML из `artifacts/` через
assistant-ui и Alfa Core Components. Исходный HTML не является runtime-кодом и
не модифицируется при переносе.

## Изменение решений

Изменения границ сервисов, владения данными или обязательного стека сначала
вносятся в Specs и отражаются в `AGENTS.md`. Текущее выполнение и зависимости
задач меняются только в `WORK_PLAN.md`.
