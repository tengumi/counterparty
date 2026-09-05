# Next steps: запуск разработки через субагентов

**Текущая цель:** пройти gate F0 и получить независимо запускаемые каркасы
четырёх приложений, contract v0 и подтверждённые рискованные интеграции.

**Источник полного backlog:** [`docs/WORK_PLAN.md`](docs/WORK_PLAN.md).

## Текущее состояние

- Specs 1.1, архитектурная карта и подробный план готовы.
- Старый `src`-прототип и корневой Python/uv-проект удалены.
- Подготовительная канва должна находиться в текущем baseline commit. Перед
  первой волной главный агент проверяет clean worktree и создаёт все task-ветки
  от этого HEAD.
- Целевые `apps/`, `services/`, `packages/`, `migrations/` и `scripts/` ещё не
  созданы.
- Дизайнерский HTML принят как UI baseline и не должен редактироваться.
- Mock JSON утверждён и используется напрямую из
  `artifacts/contractors_audit.snapshot.json`.
- Dockerfile нужен каждому из `web`, `ui_api`, `agent`, `mcp`; Compose — только
  на позднем этапе OPS-01.

Главный агент обновляет этот файл после каждой интегрированной волны. Субагенты
не меняют его без отдельного поручения.

## Режим совместной работы

```text
пользователь ↔ главный агент
                  ├─ субагент A: независимая реализация
                  ├─ субагент B: независимая реализация
                  └─ субагент C: исследование или проверка
                         ↓
               интеграция и verifier
                         ↓
        runnable срез + тесты + ограничения
                         ↓
             совместный review с пользователем
                         ↓
              скорректированная следующая волна
```

Главный агент не уходит в одну длинную реализацию и не отдаёт пользователю
сырые ответы субагентов. Он остаётся собеседником, принимает уточнения во время
волны, при необходимости прерывает/переназначает задачи и возвращает один
согласованный результат.

После каждой волны обязателен пользовательский checkpoint:

1. что стало возможно запустить или посмотреть;
2. какие параллельные результаты вошли в общий срез;
3. какие проверки прошли и что пока не проверено;
4. какие решения или ограничения требуют реакции пользователя;
5. какой состав следующей волны предлагается.

Следующая крупная волна запускается после review, если пользователь заранее не
попросил работать непрерывно. Его замечания записываются в этот файл, чтобы
следующий подход не зависел от истории чата.

## Правило запуска

В одном заходе главный агент запускает до трёх независимых субагентов, оставляя
себе роль координатора. Следующая волна стартует только после просмотра общего
diff и проверки gate предыдущей. Агенты используют общую Git-историю, но разные
worktrees и task-ветки; ownership областей всё равно не должен пересекаться.

Фактически каждый субагент работает в своём persistent Git worktree внутри
`.worktrees/`, созданном от одного baseline commit. Основной worktree остаётся у
главного агента для общения, интеграции и review. Task-ветка и worktree живут до
пользовательского принятия среза, поэтому остановленную работу можно быстро
продолжить с последнего commit/checkpoint.

Перед первой волной главный агент выполняет P0:

1. проверяет текущий diff и отсутствие секретов/generated data;
2. получает подтверждение пользователя на фиксацию подготовительной канвы, если
   команда запуска ещё не подразумевает commit;
3. создаёт baseline commit;
4. создаёт для каждой задачи branch `agent/<task-id>-<slug>` и worktree
   `.worktrees/<task-id>-<slug>`;
5. передаёт субагенту точный worktree и запрещает переключать ветку.

Все поручения используют общий prefix:

```text
Работай в выданном worktree и следуй docs/SUBAGENT_GUIDE.md.
Веди docs/checkpoints/tasks/<TASK_ID>.md и делай небольшие commits после
устойчивых шагов. Не меняй NEXT_STEPS/WORK_PLAN/AGENTS и чужую область.
```

Каждое поручение ниже уже сформулировано в достаточном объёме. Не добавляй в
prompt пересказ Specs: передай task ID, ownership и ссылки.

## Волна A — независимые основы

Запустить параллельно три задачи.

### A1 · `python_foundation`

```text
Выполни F0-01, F0-02 и F0-05: создай самостоятельные Python 3.13 packages/contracts,
packages/domain и packages/storage с pyproject, import smoke tests и contract v0.
Владеешь только packages/** и их локальными тестами. Корневой uv-проект не создавай.
Читай docs/Specs/01_ARCHITECTURE.md и общие DTO из docs/Specs/10_SYSTEM_CONTRACTS.md.
Проверь каждый пакет его локальными uv/ruff/mypy/pytest командами.
Верни результат, файлы, проверки и спорные contract assumptions.
```

### A2 · `web_foundation`

```text
Выполни F0-04 и WEB-01: создай apps/web на React/Vite/TypeScript strict,
подключи базовую Core DS тему, маршруты checks и собственный Dockerfile со smoke screen.
Владеешь только apps/web/**. Не редактируй дизайнерский artifact и не копируй support.js.
Читай docs/Specs/06_FRONTEND.md, начало docs/Specs/07_DESIGN_AND_UX.md и
artifacts/Design TZ для экранов/Проверка контрагентов v2.dc.html.
Запусти lint, typecheck, tests, production build и по возможности docker build.
Верни результат, файлы, проверки и ограничения совместимости версий.
```

### A3 · `data_contract_audit`

```text
Подготовь read-only аудит для IMP-01/DB-02: сопоставь минимальный contract v0 с реальным
mock JSON и перечисли обязательные Extended JSON wrappers, aliases, source paths и
контрольные значения для первого вертикального импорта. Код и документы не меняй.
Читай docs/Specs/02_DATA_AND_STORAGE.md, data DTO из docs/Specs/10_SYSTEM_CONTRACTS.md и
artifacts/contractors_audit.snapshot.json.
Верни компактно: подтверждено, расхождения, минимальный набор таблиц/тестов, риски.
```

### Интеграция волны A главным агентом

- проверить, что A1 и A2 не создали root `pyproject.toml`/`uv.lock`;
- сопоставить contract assumptions A1 с аудитом A3;
- при расхождении отправить короткий follow-up только A1;
- назначить verifier для contract v0, если DTO пришлось существенно менять;
- отметить A-задачи ниже; переносить `done` в WORK_PLAN только после
  пользовательского review среза.

Пользовательский срез A: показать структуру трёх shared-пакетов, запущенный web
smoke screen и короткий список подтверждённых особенностей mock JSON. Согласовать
contract v0 и внешний фундамент UI до создания сервисов.

| Task | Статус | Исполнитель/результат |
|---|---|---|
| A1 / F0-01, F0-02, F0-05 | todo | — |
| A2 / F0-04, WEB-01 | todo | — |
| A3 / IMP-01 audit | todo | — |

## Волна B — три Python-сервиса

Запускать после принятия contract v0. Все три задачи параллельны.

### B1 · `ui_api_shell`

```text
Создай самостоятельный services/ui_api для F0-03A: Python 3.13 uv-проект,
FastAPI lifespan/composition root, typed health endpoint, локальная зависимость contracts,
тест и собственный Dockerfile. Владеешь только services/ui_api/**.
Читай docs/Specs/01_ARCHITECTURE.md и docs/Specs/03_UI_BACKEND.md.
Не добавляй бизнес-endpoints и подключение БД раньше следующей задачи.
Выполни локальные lint/type/test и docker build; верни файлы, проверки, assumptions.
```

### B2 · `agent_shell`

```text
Создай самостоятельный services/agent для F0-03B и узкого V04 spike:
Python 3.13 uv-проект, FastAPI health, composition root, contracts dependency,
LangGraph PostgreSQL checkpointer adapter за локальной границей, тест и Dockerfile.
Владеешь services/agent/**; migration proposal верни текстом, migrations/** не меняй.
Читай docs/Specs/04_AGENT_SERVICE.md и V04 в docs/Specs/08_ENGINEERING_AND_ACCEPTANCE.md.
Не реализуй полный agent flow и assistant-stream. Верни результат и ограничения V04.
```

### B3 · `mcp_shell`

```text
Создай самостоятельный services/mcp для F0-03C и V05 spike: Python 3.13 uv-проект,
FastMCP Streamable HTTP, typed read-only stub tool, lifecycle/async cleanup test и Dockerfile.
Владеешь только services/mcp/**. Читай docs/Specs/05_MCP_SERVICE.md и MCP-раздел
docs/Specs/10_SYSTEM_CONTRACTS.md. Не подключай workspace и не пиши ручной MCP protocol.
Выполни lint/type/test и docker build; верни результат и ограничения V05.
```

### Интеграция волны B главным агентом

- проверить единый подход к config, health и Dockerfile без общего runtime-пакета;
- убедиться, что lockfiles принадлежат сервисам и не появился root uv config;
- передать migration proposal B2 будущему владельцу DB-01;
- независимому verifier проверить lifecycle, import side effects и container startup.

Пользовательский срез B: показать самостоятельный запуск и health каждого из
трёх Python-сервисов, результаты сборки четырёх Dockerfile и подтверждённые
ограничения V04/V05. Согласовать сервисную канву до бизнес-логики.

| Task | Статус | Исполнитель/результат |
|---|---|---|
| B1 / F0-03A | todo | — |
| B2 / F0-03B, V04 spike | todo | — |
| B3 / F0-03C, V05 spike | todo | — |

## Волна C — интеграционные риски и первый data/domain слой

После волны B запустить параллельно:

### C1 · `assistant_transport_spike`

```text
Выполни F0-06/V01: соедини assistant-stream Agent Service с assistant-ui Web
через минимальные adapters; проверь текст, typed activity, terminal error и cancel.
Владеешь только transport/adapters и их тестами в services/agent/** и apps/web/**.
Читай transport-разделы docs/Specs/04_AGENT_SERVICE.md, docs/Specs/06_FRONTEND.md
и V01 из docs/Specs/08_ENGINEERING_AND_ACCEPTANCE.md. Не пиши собственный codec.
Верни проверенную матрицу версий, тесты и оставшиеся ограничения reconnect.
```

### C2 · `storage_import_vertical`

```text
Выполни DB-01, DB-02 и IMP-01: создай Alembic base со схемами reports/workspace,
первую вертикаль report tables и Extended JSON decoder для утверждённого mock JSON.
Владеешь migrations/**, packages/storage/**, scripts/import_reports/**.
Читай docs/Specs/02_DATA_AND_STORAGE.md, нужные data DTO в 10_SYSTEM_CONTRACTS.md
и используй результат A3. Не создавай копию JSON и не добавляй Compose.
Проверь migration upgrade/downgrade и decoder на контрольных значениях.
```

### C3 · `domain_evidence`

```text
Выполни D-01 и D-02: validation идентификаторов, Decimal/date/missing helpers,
Evidence ledger и проверку разрешимости refs как чистый domain-код без I/O.
Владеешь packages/domain/** и локальными тестами; contracts только читаешь.
Читай data/evidence разделы docs/Specs/02_DATA_AND_STORAGE.md и
docs/Specs/10_SYSTEM_CONTRACTS.md. Верни покрытые edge cases и assumptions.
```

| Task | Статус | Исполнитель/результат |
|---|---|---|
| C1 / F0-06, V01 | todo | — |
| C2 / DB-01, DB-02, IMP-01 | todo | — |
| C3 / D-01, D-02 | todo | — |

Пользовательский срез C: показать минимальный живой stream между Agent и Web,
применение/откат первой миграции, чтение реального mock JSON и unit-проверку
evidence refs. Это первый интегрированный технический срез, а не набор scaffold.

## Gate F0

Перед переходом к продуктовой волне главный агент подтверждает:

- `web`, `ui_api`, `agent`, `mcp` имеют собственные собираемые Dockerfile;
- каждый Python-сервис синхронизируется своим uv lockfile;
- shared packages импортируются без I/O side effects;
- contract v0 покрывает IDs, outcomes, availability и evidence refs;
- V01, V04, V05 подтверждены тестами либо имеют локализованные ограничения;
- mock JSON читается напрямую из artifacts;
- root не содержит Python/Node runtime-конфигурации и Compose.

Если gate пройден, следующий набор формируется из волны 1
[`docs/WORK_PLAN.md`](docs/WORK_PLAN.md#4-волна-1--данные-базовый-продукт-и-ui-параллельно):

- UI API: API-01…API-04;
- Data: DB-03, DB-04, IMP-02, IMP-03;
- Web: WEB-02…WEB-07;
- Agent/MCP: MCP-01/MCP-02 и AG-01/AG-02 после готовности зависимостей.

Главный агент формулирует эти поручения по тому же короткому шаблону и не
копирует сюда весь WORK_PLAN заранее.

## Последующие MVP-срезы

После F0 проект строится ещё несколькими подходами, каждый с параллельной
реализацией и review пользователя:

1. **Read-only продуктовый срез:** импорт всех mock-отчётов, проект с одной
   компанией, overview API и S1/S2 UI с открываемым evidence.
2. **Агентный срез:** внутренний MCP, grounded ответ, сохраняемый thread,
   reconnect/cancel и первый реальный разговор по компании А.
3. **Документный срез:** upload, skill execution, точная ссылка на PDF/XLSX,
   follow-up во время tool и устаревание прежнего вывода.
4. **Решение и сравнение:** решение пользователя, сравнение пяти компаний,
   возвращение в проект и ошибки/неполные данные.
5. **Финальная сборка:** Compose, сквозные браузерные сценарии, V01–V13,
   agent evals и demo runbook.

На review каждого среза пользователь может изменить приоритет, UX или глубину
следующего шага. Главный агент пересобирает только будущие поручения и сохраняет
уже проверенные основания.

## Нерешённые вопросы, которые не блокируют F0

- Конкретный model provider/model ID для real-model evals.
- Финальная политика отображения raw YELLOW/RED ЗСК.
- Внешний MCP/export и whitelist полей; основной MVP использует внутренний MCP.
