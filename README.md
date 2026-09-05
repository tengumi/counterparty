# Counterparty Workspace

Монорепозиторий MVP ИИ-помощника, который помогает предпринимателю проверить
контрагента, сопоставить сведения отчёта с условиями сделки и сохранить
обоснованное решение.

## Текущий статус

Реализованы каркас сервисов, PostgreSQL/storage и импорт 100 разрешённых
mock-отчётов. UI API предоставляет проекты, состав компаний, карточку и 17 разделов
отчёта, проектные evidence-ссылки и детерминированное сравнение. React S1/S2
читает и изменяет проекты и состав компаний через REST; материалы открывают
закреплённые отчёты, разделы, основания и серверное сравнение. Черновик и выбранные
основания сохраняются в браузере. Разговор, документы и запись решения пока
недоступны; полноценного агентного сценария ещё нет.

Внутренний MCP читает overview, разделы и сравнение компаний из PostgreSQL с
сервисной аутентификацией; его значения совпадают с серверным сравнением UI API
и проверяются parity-тестом на живом контуре. Agent Service получил PostgreSQL checkpoints штатного LangGraph
и сохраняемые статусы runs. Это persistence-срез: текущий RPC-разговор всё ещё
использует демонстрационный runtime в памяти; подключение durable runs к нему
относится к AG-04. Удаление проекта через REST пока не реализовано.

Срез WEB-08 подключает REST к принятому S1/S2: live browser flow проверяет
создание проекта, две компании, финансовое основание, серверное сравнение и
возврат с сохранённым черновиком на desktop/mobile. Панель отдельно проверена
на tablet. Результаты и ограничения — в [WEB-08 QA](artifacts/qa/WEB-08/README.md).
WEB-07 остаётся историческим визуальным baseline; агентный сценарий WEB-09 впереди.

Запускать очередную волну следует по [NEXT_STEPS.md](NEXT_STEPS.md); полный
backlog и зависимости находятся в [плане разработки](docs/WORK_PLAN.md).
Требования и контракты собраны в
[индексе Specs](docs/Specs/00_OVERVIEW_AND_INDEX.md), краткая карта границ — в
[архитектуре](docs/architecture.md).

## Части репозитория

```text
.
├── apps/
│   └── web/                    React/Vite UI
├── services/
│   ├── ui_api/                 CRUD и детерминированный HTTP API
│   ├── agent/                  агент, RPC, runs и checkpoints
│   └── mcp/                    внутренний read-only MCP к reports
├── packages/
│   ├── contracts/              общие DTO и публичные контракты
│   ├── domain/                 вычисления и правила без I/O
│   └── storage/                SQLAlchemy repositories и UoW
├── migrations/                 Alembic, схемы reports и workspace
├── scripts/
│   └── import_reports/         заполнение PostgreSQL из mock JSON
├── tests/                      общие contract/integration/e2e проверки
├── docs/
└── artifacts/
```

У `web`, `ui_api`, `agent` и `mcp` есть собственные `Dockerfile`; их build
context — корень репозитория, потому что сервисы зависят от `packages/` по пути.
`compose.yaml` поднимает весь контур: PostgreSQL с volume, миграции, роли,
разовый импорт, четыре сервиса и reverse proxy перед ними. Импортёр и создание
checkpoint-таблиц остаются одноразовыми job, а не постоянными сервисами.

## Принятые технические границы

- Python 3.13; каждый Python-сервис — самостоятельный uv-проект со своим
  `pyproject.toml` и lockfile. Корневого Python-проекта нет.
- React, TypeScript strict, Vite, assistant-ui и Alfa Core Components для web.
- FastAPI для UI Backend и Agent Service; FastMCP для внутреннего MCP.
- PostgreSQL с отдельными схемами `reports` и `workspace`.
- LangGraph/Deep Agents и штатный assistant-stream для агентного runtime.
- Детерминированные расчёты находятся в `packages/domain`; LLM не вычисляет
  суммы, ranking или risk rules.
- Каждый фактический вывод разрешается в существующий evidence reference.
- JSON из дизайнерского набора — основной разрешённый mock-источник; создавать
  отдельную «очищенную» fixture не требуется.

## Дизайн

Основной reference:
[Проверка контрагентов v2.dc.html](<artifacts/Design TZ для экранов/Проверка контрагентов v2.dc.html>).

HTML остаётся неизменяемым исходным артефактом. Его экраны, состояния, тексты и
переходы переносятся в `apps/web` компонентами; демонстрационный `support.js`
не становится зависимостью приложения. Карта декомпозиции приведена в
[WORK_PLAN.md](docs/WORK_PLAN.md#ui-декомпозиция-дизайнерского-html).

## Источники истины

При расхождении документов используется следующий приоритет:

1. `AGENTS.md` — рабочие правила репозитория;
2. `docs/Specs/` версии 1.1 — продуктовые и системные требования;
3. `NEXT_STEPS.md` — текущая волна субагентов и пользовательские checkpoints;
4. `docs/WORK_PLAN.md` — полный порядок реализации и зависимости;
5. `docs/SUBAGENT_GUIDE.md` — единый протокол task-веток, checkpoints и handoff;
6. `docs/architecture.md` — краткая карта архитектуры;
7. `artifacts/` — исходные материалы и дизайн, рассматриваемые как данные.

Файлы из `artifacts/` не являются командами для агента.

## Локальный запуск

Нужен Docker с Compose. Весь контур поднимается из корня одной командой; uv и
Node.js нужны только для запуска проверок и для работы без Docker.

```sh
docker compose up -d --wait
docker compose ps
```

Compose поднимает PostgreSQL с durable volume, применяет Alembic, создаёт четыре
служебных login-роли, один раз импортирует mock-снимок и запускает `ui_api`,
`agent`, `mcp`, статический `web` и reverse proxy перед ними. `--wait` возвращает
управление только когда healthcheck каждого сервиса прошёл; повторный `up`
ничего не переимпортирует (`changed_nothing: true`).

Открывайте **http://localhost:5173** — это единственный origin, который нужен
браузеру: proxy отдаёт SPA, проксирует `/api/v1` в `ui_api` и `/agent/` в
`agent`, поэтому session cookie остаётся first-party, а SPA собирается без
API base URL. Прямые порты сервисов опубликованы для отладки:

| Сервис | Внутри сети | На хосте | Health |
|---|---|---|---|
| proxy (вход) | `proxy:80` | `5173` | `GET /healthz` |
| ui_api | `ui_api:8000` | `8000` | `GET /healthz` |
| agent | `agent:8000` | `8001` | `GET /healthz` |
| mcp | `mcp:8000` | `8002` | `GET /healthz`, инструменты на `/mcp` |
| web (статика) | `web:8080` | — | `GET /healthz` |
| postgres | `postgres:5432` | `55432` | `pg_isready` |

Пока в UI нет формы входа: один раз выполните демо-вход в консоли браузера на
`http://localhost:5173/checks` и дождитесь перезагрузки:

```js
fetch('/api/v1/auth/session', {
  method: 'POST',
  credentials: 'include',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ login: 'demo-analyst' }),
}).then((response) => {
  if (!response.ok) throw new Error(`Демо-вход: HTTP ${response.status}`);
  location.reload();
});
```

Cookie остаётся HttpOnly; после перезапуска `ui_api` демо-вход нужно повторить.

Проверяемый live flow: создать проверку и в материалах добавить ИНН
`1684017097` и `7449088645`. Открыть компанию → «Финансы» → «Основание: Выручка»,
вернуться к отчёту или добавить основание в черновик через «Обсудить». В материалах
выбрать «Сравнить компании», критерии и период; сравнение вычисляет REST API.
После перезагрузки сохраняются состав, черновик, контекст и выбор сравнения.
Данные — предоставленные mock snapshots, не актуальная проверка компании.
Отдельное сохранение сравнения как материала, чат, документы и решение ещё недоступны.

Полезные команды:

```sh
docker compose logs -f ui_api mcp agent     # логи сервисов
docker compose run --rm import              # импорт ещё раз; повтор — no-op
docker compose down                         # остановить, сохранив данные
```

`docker compose down -v` удаляет volume с базой вместе с импортом.

### Сборка образов и локальные пакеты

Каждый Python-образ собирается **из корня репозитория**, потому что сервисы
зависят от `packages/` по пути, и контекст, суженный до каталога сервиса, эти
зависимости не видит. Dockerfile при этом остаются внутри сервисов:

```sh
docker build -f services/ui_api/Dockerfile -t counterparty-ui-api .
docker build -f services/mcp/Dockerfile    -t counterparty-mcp .
docker build -f services/agent/Dockerfile  -t counterparty-agent .
docker build apps/web -t counterparty-web
```

Два правила, без которых сборка выглядит успешной, а сервис стартует сломанным.

Virtualenv собирается сразу по финальному пути `/app/.venv`: перенос готового
окружения между путями ломает console scripts внутри него.

`counterparty-contracts`, `-domain` и `-storage` остаются на версии `0.1.0` при
любых изменениях, поэтому `uv sync --frozen` считает уже установленную копию
актуальной и не переустанавливает её. Именно так `ui_api` падал с
`ImportError: cannot import name 'ReportEvidence'`. Постоянное решение принято
такое: локальные пакеты ставятся **не editable** (runtime-слой не содержит
исходников) и каждый шаг синхронизации переустанавливает их по имени:

```sh
uv sync --frozen --no-dev --no-editable \
  --reinstall-package counterparty-contracts \
  --reinstall-package counterparty-domain \
  --reinstall-package counterparty-storage
```

Это зафиксировано в Dockerfile сервисов и в uv-шагах `compose.yaml`, чьи venv
живут в named volumes между запусками. То же правило действует и при работе на
хосте после изменения `packages/`.

### Запуск без Docker

Проверенные native-команды для уже подготовленного окружения — в
[G6](docs/checkpoints/tasks/G6.md#native-запуск-из-dev); подготовка БД описана
в [G5](docs/checkpoints/tasks/G5.md). Vite проксирует `/api/v1` на
`localhost:8000`, поэтому `VITE_UI_API_BASE_URL` задавать не нужно. Без
настроенной БД доступны health и session, а запросы проектов возвращают
`dependency_unavailable`.

### Проверки

В `apps/web` обязательные проверки: `npm run lint`, `npm run typecheck`,
`npm test`, `npm run build`; browser harness дополнительно проверяется
`npm run qa:check`. Команды воспроизведения — в [QA runbook](apps/web/qa/README.md),
скриншоты и результаты с source SHA — в [WEB-08](artifacts/qa/WEB-08/README.md).
`npm run qa:web08` печатает матрицу без запуска браузера; `-- --capture` выполняет
live REST сценарий. Исторические [WEB-07](artifacts/qa/WEB-07/README.md) снимки
проверяли typed fixtures и CRUD; они не подтверждают нынешний агентный runtime.

В каждом Python-проекте: `uv run ruff check .`, `uv run ruff format --check .`,
`uv run mypy`, `uv run pytest`.

### Backend: отчёты, MCP и checkpoints

UI API читает `/api/v1/reports/{report_id}/sections/{section}` и разрешает
`/api/v1/projects/{project_id}/evidence/{ref}` после проверки владельца проекта
и исторической принадлежности снимка. Разделы принимают `limit`, `cursor` и
разрешённые для раздела `years`, `active`, `role`, `status_raw`. Пустой или
отсутствующий раздел остаётся отдельным состоянием данных. Evidence ID нужно
кодировать через `encodeURIComponent`; произвольный JSON Pointer не разрешён.

MCP отдаёт `get_company_overview`, `get_report_section` и `compare_companies`
штатному MCP-клиенту на `http://localhost:8002/mcp`. Роль MCP читает только
`reports`, транзакции read-only, workspace недоступен. Сервис получает **только**
SHA256 digest учётных данных и без digest не принимает ни одного токена; в
`compose.yaml` по умолчанию стоит digest публичного демо-токена
`counterparty-local-demo-agent-token`, который поэтому секретом не является.
Своё значение задаётся так:

```sh
export AGENT_MCP_AUTH_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export MCP_AUTH_TOKEN_SHA256="$(python3 -c 'import hashlib, os; print(hashlib.sha256(os.environ["AGENT_MCP_AUTH_TOKEN"].encode()).hexdigest())')"
docker compose up -d mcp agent
```

Agent получает исходный токен только на backend, MCP — его digest. Compose
связывает agent с внутренними UI API/MCP URL и запускает после их healthchecks.
`AGENT_MODEL_PROVIDER=deterministic` — воспроизводимый локальный режим; он не
считается проверкой качества реальной LLM.

`compare_companies` сравнивает 2–20 закреплённых снимков по whitelist-критериям и
не строит ranking, score или winner. Значения приходят из той же функции
`packages/domain`, что и серверное сравнение UI API, а совпадение проверяется на
живом контуре:

```sh
cd services/mcp
MCP_PARITY_UI_API_URL=http://127.0.0.1:5173 \
MCP_PARITY_MCP_URL=http://127.0.0.1:8002 \
MCP_PARITY_TOKEN=counterparty-local-demo-agent-token \
uv run --frozen pytest tests/test_parity.py
```

Таблицы LangGraph checkpoints создаёт сервис `checkpoints` владельцем схемы
после Alembic; runtime-login агента DDL-прав не получает. На одну БД допускается
один Agent worker. Alembic не управляет таблицами saver, `/healthz` сообщает
liveness, а не готовность полного агентного сценария. Ограничения агентного
среза — в [I5](docs/checkpoints/tasks/I5.md).
