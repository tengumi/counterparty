# План параллельной разработки MVP

**Статус:** F0 и волна 1 приняты; начат первый срез волны 2 (REST/MCP/persistence)

**Основание:** Specs 1.1 и принятый дизайнерский HTML

**Обновлено:** 5 сентября 2026

## 1. Как пользоваться планом

Задача берётся в работу только после выполнения её `depends on`. Исполнитель
меняет прежде всего указанную область файлов. Общие контракты, миграции и
конфигурация репозитория — точки синхронизации: их изменения оформляются отдельной
задачей и не смешиваются с реализацией конкретного сервиса.

Статусы: `todo`, `in progress`, `blocked`, `review`, `done`. Оперативный прогресс
текущей волны ведётся в `NEXT_STEPS.md`. В этом плане `done` фиксируется после
пользовательского review принятого среза; подробный дневник сюда не добавляется.

Готовность задачи означает работающий результат и тест, а не только созданные
папки. Каждый сервис сначала запускается самостоятельно. Общий `compose.yaml`
собирается после появления самостоятельных образов всех четырёх развёртываемых
частей.

## 2. Карта потоков

| Поток | Владеет | Не владеет |
|---|---|---|
| Foundation | структура, шаблоны сервисов, общие команды и CI | бизнес-логика сервисов |
| Contracts | `packages/contracts` | ORM, HTTP handlers, UI state |
| Data | `packages/storage`, `migrations`, `scripts/import_reports` | агентный prompt, React |
| Domain | `packages/domain` | сеть, БД, FastAPI |
| UI API | `services/ui_api` | agent runtime, MCP transport |
| Agent | `services/agent` | прямое чтение `reports`, решение пользователя |
| MCP | `services/mcp` | `workspace`, документы и память чата |
| Web | `apps/web` | секреты, прямой доступ к БД/MCP |
| QA | `tests`, contract/e2e harness | изменение продукта без отдельной задачи |

Одновременно можно вести Web, Data/Domain и Agent spike после короткого этапа
F0. UI API и MCP начинают интеграцию после появления первой версии contracts и
storage. Изменения contract v0 согласуются до параллельного продолжения, чтобы
команда не редактировала один набор DTO в разных ветках.

## 3. Этап F0 — каркас и рискованные интеграции

| ID | Результат | Depends on | Область | Статус |
|---|---|---|---|---|
| F0-01 | Соглашения Python 3.13 и шаблон самостоятельного uv-проекта без Python-конфига в корне | — | docs/tooling | done |
| F0-02 | Пустые устанавливаемые `contracts`, `domain`, `storage` с import smoke tests | F0-01 | `packages/` | done |
| F0-03A | `ui_api`: отдельные pyproject/lockfile, health endpoint, собственный Dockerfile и smoke test образа | F0-01, F0-02 | `services/ui_api` | done |
| F0-03B | `agent`: отдельные pyproject/lockfile, health endpoint, собственный Dockerfile и smoke test образа | F0-01, F0-02 | `services/agent` | done |
| F0-03C | `mcp`: отдельные pyproject/lockfile, health endpoint, собственный Dockerfile и smoke test образа | F0-01, F0-02 | `services/mcp` | done |
| F0-04 | React/Vite/TypeScript strict, Core DS foundation, собственный Dockerfile и статический smoke screen | — | `apps/web` | done |
| F0-05 | Contract v0: IDs, source/evidence refs, availability/outcome, project/thread/run envelopes | F0-02 | `packages/contracts` | done |
| F0-06 | Spike V01: assistant-stream ↔ assistant-ui передаёт текст, typed activity, terminal error и cancel | F0-03B, F0-04, F0-05 | `agent`, `web`, contract test | done |
| F0-07 | Spike V04: LangGraph PostgreSQL checkpoint в схеме `workspace`, restart помечает run interrupted | F0-03B | `agent`, `migrations` | done |
| F0-08 | Spike V05: FastMCP Streamable HTTP, один typed read-only tool и корректный async cleanup | F0-03C, F0-05 | `mcp`, integration test | done |

Gate F0:

- четыре Dockerfile собираются независимо;
- три Python health checks и web smoke screen работают без Compose;
- contract v0 подключается сервисами как версионируемая локальная зависимость;
- V01, V04 и V05 либо подтверждены тестом, либо имеют локализованный adapter и
  записанное ограничение;
- mock JSON используется напрямую из artifacts, без производной fixture-копии.

## 4. Волна 1 — данные, базовый продукт и UI параллельно

### Contracts и domain

| ID | Результат | Depends on | Статус |
|---|---|---|---|
| C-01 | DTO отчёта: company/report identity, money/date values, raw enums, source paths | F0-05 | done |
| C-02 | REST DTO проектов, компаний, threads, условий и решений | F0-05 | done |
| C-03 | Agent public state, commands, pending command и activity DTO | F0-06 | done |
| C-04 | MCP overview/section/comparison DTO и пагинация | F0-08, C-01 | done |
| D-01 | ИНН/ОГРН validation, Decimal/date helpers и missing/zero semantics | C-01 | done |
| D-02 | Evidence ledger и проверка разрешимости refs | C-01 | done |
| D-03 | Детерминированные summary, finance/proceeding calculations | D-01, D-02 | done |
| D-04 | Сравнение 2–20 компаний без общего score/winner | D-03 | done |

### Data

| ID | Результат | Depends on | Статус |
|---|---|---|---|
| DB-01 | Alembic base с отдельными схемами `reports` и `workspace` | F0-01 | done |
| DB-02 | Таблицы import batch, company, report и первая вертикаль report entities | DB-01, C-01 | done |
| DB-03 | Таблицы project, project_company, thread и idempotency key | DB-01, C-02 | done |
| DB-04 | Async repositories/UoW и отдельные права importer, UI API, MCP, Agent | DB-02, DB-03 | done |
| IMP-01 | Extended JSON decoder и schema fingerprint для существующего mock JSON | C-01, D-01 | done |
| IMP-02 | Идемпотентный `scripts/import_reports` с batch/hash и отчётом ошибок | DB-02, DB-04, IMP-01 | done |
| IMP-03 | Импорт всех 100 mock snapshots и сверка контрольных примеров Specs | IMP-02 | done |

### UI API

| ID | Результат | Depends on | Статус |
|---|---|---|---|
| API-01 | Demo auth/session и project ownership dependency | F0-03A, C-02 | done |
| API-02 | Create/list/open/rename project и первый thread, идемпотентность request ID | API-01, DB-03, DB-04 | done |
| API-03 | Add/remove 1–20 companies с закреплением report_id | API-02, IMP-02 | done |
| API-04 | Deterministic company overview с evidence refs | API-03, D-03 | done |
| API-05 | Comparison endpoint и неполные данные | API-04, D-04 | done |
| API-06 | Чтение разделов отчёта и project-scoped evidence по REST; фильтры, cursor и границы доступа | API-04, C-01, DB-04 | done |

### Web — визуальный каркас без ожидания backend

| ID | Результат | Depends on | Статус |
|---|---|---|---|
| WEB-01 | App shell, маршруты `/checks` и `/checks/:projectId/chats/:threadId` | F0-04 | done |
| WEB-02 | S1: поле задачи, примеры и список сохранённых проверок | WEB-01 | done |
| WEB-03 | S2 shell: header, chat switcher, company context strip, responsive layout | WEB-01 | done |
| WEB-04 | Conversation blocks, activity/progress и composer states на typed mocks | WEB-03, F0-05 | done |
| WEB-05 | Materials panel navigation и локальное сохранение drawer/draft/scroll | WEB-03 | done |
| WEB-06 | Company report и evidence detail по typed mocks | WEB-05, C-01 | done |
| WEB-07 | Visual regression/screenshots 390, 1024, 1440 px против HTML reference | WEB-02…WEB-06 | done |

Gate волны 1: mock JSON импортируется в PostgreSQL; API возвращает одну реальную
по mock-данным карточку с разрешимыми refs; React реализует S1/S2 и материалы с
typed mocks; скриншоты подтверждают сохранение принятого дизайна.

## 5. Волна 2 — MCP, агент, документы и живая интеграция

| ID | Результат | Depends on | Поток | Статус |
|---|---|---|---|---|
| MCP-01 | `get_company_overview` с pinned report_id | C-04, DB-04, IMP-02 | MCP | done |
| MCP-02 | `get_report_section`, enum filters, cursor и truncation | MCP-01 | MCP | done |
| MCP-03 | `compare_companies` и parity с UI API | MCP-02, API-05 | MCP/QA | todo |
| AG-01 | LangChain model adapter и сконфигурированный Deep Agents harness поверх checkpointer F0-07; собственный agent loop не пишется | F0-06, F0-07 | Agent | todo |
| AG-02 | Project/thread context assembly без соседних histories | AG-01, API-02 | Agent | todo |
| AG-03 | Подключение MCP tools штатным механизмом Deep Agents, evidence-grounded answer и прикладной validator/repair | AG-02, MCP-02, D-02 | Agent | todo |
| AG-04 | Persistent run registry, reconnect, cancel и public projection | AG-03, C-03 | Agent | todo |
| AG-05 | Persistent follow-up inbox и safe-boundary apply | AG-04 | Agent | todo |
| AG-06 | Справочник знаний агента по Specs 04 §6: version, источник, тестовые примеры и внутренний lookup без vector search | AG-03 | Agent/Domain | todo |
| DOC-01 | Upload/storage metadata и project-scoped access | API-02 | UI API/Data | todo |
| DOC-02 | SkillExecutor, MarkItDown/PDF adapters, fragments и locators | DOC-01, AG-02 | Agent | todo |
| DOC-03 | XLSX/DOCX/PDF parsing policies, cache и trace | DOC-02 | Agent/QA | todo |
| WEB-08 | REST integration: projects, overview, materials, comparison | API-04, API-05, API-06, WEB-07 | Web | done |
| WEB-09 | Agent transport: stream, reconnect, cancel и errors | AG-04, WEB-04 | Web | todo |
| WEB-10 | Follow-up queued/applied и document attachments | AG-05, DOC-02, WEB-09 | Web | todo |
| WEB-11 | Decision flow, outdated analysis и returning-user state | WEB-08, WEB-09 | Web | todo |

Gate волны 2: основной сценарий компании А проходит через реальные сервисы;
закрытие страницы не отменяет run; follow-up не создаёт второго writer;
evidence открывает точный источник; решение пользователя записывается только
через UI API.

### Граница MVP, принятая 05.09.2026

Пользователь сократил объём MVP до сквозной истории «агент отвечает по
закреплённому отчёту с проверяемыми evidence refs». В MVP остаются AG-01…AG-04,
MCP-03, WEB-09, WEB-11, OPS-01, сжатая приёмка и REL-01.

Перенесены в post-MVP и не входят в gate: DOC-01, DOC-02, DOC-03 (документы и
skills), AG-05 (persistent follow-up inbox) и WEB-10 (follow-up и вложения).
Их depends on и формулировки не меняются; при возврате к ним skills и файловый
backend берутся штатными механизмами Deep Agents по Specs 11.

Gate волны 2 в сокращённом виде: основной сценарий компании А проходит через
реальные сервисы; закрытие страницы не отменяет run; evidence открывает точный
источник; решение пользователя записывается только через UI API. Пункт про
второго writer при follow-up проверяется вместе с AG-05 в post-MVP.

Глубина проверки, принятая тем же решением: независимые проверяющие агенты
назначаются только на AG-03 и AG-04; остальные задачи закрываются тестами
исполнителя и обзором главного агента.

Уточнение 05.09.2026 после вопроса пользователя о качестве агента: сокращение
объёма неявно вынесло из плана и качество поведения. QA-04 зависела от AG-05 и
DOC-03 и ушла вместе с ними, а справочник знаний из Specs 04 §6 вообще не был
задачей плана. Обе позиции возвращены: заведена AG-06, QA-04 переподчинена
AG-04 и AG-06. Пользователь решил закончить остальное и добавить их следом,
поэтому обе идут после волны J и не входят в её объём. Без AG-06 агент даёт
корректные ссылки при неверных выводах: банковский светофор смешивается с
финансовой состоятельностью, агрегат по арбитражу читается как предмет спора,
годовая отчётность — как текущий остаток.

Модель и провайдер подключает пользователь самостоятельно. Значение по умолчанию
остаётся детерминированным адаптером, model ID не хардкодится (Specs 09).

## 6. Волна 3 — сборка системы и приёмка

Остаток MVP (AG-04, недостающие REST Specs 10 §5, OPS-01 live bring-up, сквозная
приёмка, REFACTOR-01) ведётся одним консолидированным заходом главного агента,
без деления на параллельные волны. Оперативный порядок — в `NEXT_STEPS.md`.

| ID | Результат | Depends on | Статус |
|---|---|---|---|
| OPS-01 | Общий `compose.yaml`, reverse proxy, PostgreSQL volume и service healthchecks | F0-03A…F0-03C, F0-04, волна 2 | done (06.09.2026: полный `up -d`, миграция 0006, 6 сервисов healthy, ручной проход через proxy) |
| REFACTOR-01 | Развести плоскую раскладку `services/ui_api` на подпакеты; только перемещение файлов и правка импортов, поведение и тесты без изменений | WEB-09, WEB-11 | todo |
| QA-01 | Contract tests REST/RPC/MCP и generated/checked TS types | C-01…C-04 | todo |
| QA-02 | Интеграция importer + PostgreSQL + API + MCP | IMP-03, MCP-03 | todo |
| QA-03 | Browser flow: reconnect, cancel, document, evidence, decision | WEB-11, OPS-01 | todo |
| QA-04 | Agent evals из Specs 08 §52, deterministic mocks и малый набор real-model runs; шесть из восьми сценариев не требуют документов и выполнимы без DOC | AG-04, AG-06 | todo |
| QA-05 | Security/ownership, PII-safe logs, limits и failure states | OPS-01 | todo |
| REL-01 | Все V01–V13 и F01–F21, остаточные ограничения и demo runbook | QA-01…QA-05 | todo |

Slim-часть OPS-01 выполнена в волне F: текущий `compose.yaml` поднимает
PostgreSQL, миграции, роли и импорт. Статус OPS-01 остаётся `todo`, пока в общий
контур не включены `web`, `ui_api`, `agent`, `mcp`, reverse proxy и service
healthchecks.

## 7. UI-декомпозиция дизайнерского HTML

Источник:
[`Проверка контрагентов v2.dc.html`](<../artifacts/Design TZ для экранов/Проверка контрагентов v2.dc.html>).
Файл и `support.js` остаются неизменяемыми артефактами. Inline styles и
демонстрационный state machine не переносятся одним монолитным компонентом.

Предлагаемая компонентная карта:

```text
AppShell
├── BankNavigation
├── ChecksHome (S1)
│   ├── StartComposer
│   └── CheckList
└── CheckWorkspace (S2)
    ├── WorkspaceHeader
    │   └── ChatSwitcher
    ├── CompanyContextBar
    ├── Conversation
    │   ├── UserMessage
    │   ├── AgentMessage
    │   ├── ActivityMessage
    │   ├── ConclusionMessage
    │   └── ResumeCard
    ├── Composer
    │   ├── ContextAttachment
    │   └── AttachmentMenu
    └── MaterialsPanel
        ├── MaterialsIndex
        ├── CompanyReport
        ├── EvidenceDetail
        ├── DocumentDetail
        ├── DealTermEditor
        ├── ComparisonTable
        ├── AnalysisMemo
        └── DecisionForm
```

Правила переноса:

1. Сначала воспроизводятся layout, типографика, состояния и переходы; затем
   подключаются REST/RPC данные без переписывания визуальных компонентов.
2. Токены и доступные primitives берутся из Core DS. Локальный CSS отвечает за
   layout, которого нет в DS; SVG из артефакта не копируется повторно, если
   иконка доступна установленным пакетом.
3. Состояние проектов и материалов приходит через TanStack Query; сообщения и
   run state принадлежат assistant-ui runtime; drawer, scroll и draft остаются
   локальными. Не создаётся третья копия conversation state.
4. Числа и тексты из HTML — demo data. Компоненты получают typed props и не
   хардкодят бизнес-значения.
5. Поведение HTML считается принятым визуальным baseline. Если оно расходится с
   безопасностью или системным контрактом Specs, сохраняется внешний UX, а
   backend semantics берётся из Specs; расхождение фиксируется отдельной задачей.
6. Для каждого крупного состояния сохраняется screenshot/Storybook scenario:
   S1, S2, active run, queued follow-up, materials, evidence, report, comparison,
   decision, stale result, upload failure и returning user.

## 8. Выполнение через субагентов

Оперативные волны, короткие готовые поручения, ownership файлов и обязательные
пользовательские checkpoints находятся в корневом
[`NEXT_STEPS.md`](../NEXT_STEPS.md). Этот документ хранит полный backlog и
зависимости, но не дублирует текущее распределение исполнителей.
Все исполнители работают по единому
[`SUBAGENT_GUIDE.md`](SUBAGENT_GUIDE.md): отдельный worktree/branch, компактный
task-checkpoint, небольшие commits и воспроизводимый handoff.

Не начинать одновременно полноценные API handlers, MCP tools и UI integration,
пока не принят contract v0. UI до интеграции продолжает на typed mocks. После
каждой волны главный агент собирает runnable срез, показывает его пользователю
и корректирует следующую волну по обратной связи.

## 9. Решения, не требующие нового обсуждения

- Dockerfile создаётся для каждого сервиса и web, Compose — позже.
- `scripts/import_reports` — обычный скрипт заполнения БД, не сервис.
- Используется существующий mock JSON; отдельная sanitized fixture не создаётся.
- Дизайнерский HTML принимается на вооружение и декомпозируется, а не
  переделывается с нуля.
- Внешний MCP/OAuth не блокирует основной MVP.

Вопрос о конкретном model provider/model ID блокирует только real-model evals,
но не каркас, domain, данные, UI и интеграцию через deterministic adapter.
