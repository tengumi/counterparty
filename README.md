# Counterparty Workspace

Монорепозиторий MVP ИИ-помощника, который помогает предпринимателю проверить
контрагента, сопоставить сведения отчёта с условиями сделки и сохранить
обоснованное решение.

## Быстрый старт

Нужен только Docker с Compose.

```sh
make up      # собрать образы и поднять весь контур (ждёт healthcheck'ов)
make seed    # создать демо-проверку с двумя компаниями и напечатать её URL
make open    # открыть http://localhost:5173/checks
```

Открывается **http://localhost:5173**. При первом заходе нажмите «Войти в демо».
`make help` — список команд; `make reset` — чистая база с переимпортом;
`make test` — все проверки. Подробности — раздел «Локальный запуск» ниже.

## Текущий статус

Реализованы каркас сервисов, PostgreSQL/storage и импорт 100 разрешённых
mock-отчётов. UI API предоставляет проекты, состав компаний, карточку и 17 разделов
отчёта, проектные evidence-ссылки и детерминированное сравнение. React S1/S2
читает и изменяет проекты и состав компаний через REST; материалы открывают
закреплённые отчёты, разделы, основания и серверное сравнение. Черновик и выбранные
основания сохраняются в браузере.

Агентный разговор подключён к живому RPC (DeepSeek через NeuralDeep как
provider-конфиг): ответ помощника рендерится из Markdown, каждый факт —
кликабельный чип «Основание N», история копится по всем прогонам треда и
переживает reload. Задача с S1 уходит одним кликом. Документы, upload и запись
решения через сервис ещё не подключены; UI на их месте честно деградирует.

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
├── Makefile                    единая точка входа: up / seed / test / …
├── scripts/
│   ├── import_reports/         заполнение PostgreSQL из mock JSON
│   └── seed_demo.sh            демо-вход + проект с двумя компаниями
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
make up            # = docker compose up -d --build --wait; см. Makefile
docker compose ps  # или make ps
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

Вход: на `http://localhost:5173/checks` нажмите **«Войти в демо»** — SessionGate
поставит демо-сессию и перезагрузит страницу (при 401 повторит вход, не теряя
форму). Cookie HttpOnly; после `docker compose restart ui_api` вход нужен снова.
`make seed` делает то же из терминала и сразу создаёт демо-проверку.

Что можно потыкать (`make seed` уже создаёт проект с двумя компаниями):

- **Разговор.** С S1 введите вопрос и нажмите «Отправить» один раз — задача
  улетает сама, ответ помощника приходит в Markdown с чипами «Основание N»;
  клик по чипу открывает основание. Продолжайте диалог — история копится и
  переживает reload. Пустой проект просит добавить компанию.
- **Отчёт компании.** Клик по названию компании в строке под шапкой открывает
  полноэкранный отчёт (`pReport`): переключатель Компания / Сравнение, разделы,
  «Основание: …» открывает основание drawer'ом поверх.
- **Сравнение.** «Сравнить» в строке или в отчёте: критерии, период, таблица
  считается REST API — без ranking и «победителя».
- **Материалы-панель.** Кнопка «Материалы»: состав компаний, условия/документы
  (пока unavailable), «Итог» → форма записи решения (сервис ещё не принимает).

После перезагрузки сохраняются история диалога, состав, черновик, контекст и
выбор сравнения. Данные — предоставленные mock snapshots, не актуальная проверка
компании. Документы, upload и сохранение решения через сервис пока недоступны.

Полезные команды (`make help` — полный список):

```sh
make logs                                   # логи сервисов
make ps                                     # статус контейнеров
make rebuild                                # пересобрать web/ui_api/agent/mcp
make seed                                   # ещё одна демо-проверка
docker compose run --rm import              # импорт ещё раз; повтор — no-op
make down                                   # остановить, сохранив данные
make reset                                  # то же, что `down -v` + `up` — чистая база
```

`make down` = `docker compose down` (данные целы); `make reset` /
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

В `services/agent` pytest проверяет общие контракты и инфраструктуру.
Хрупкие тесты ответов, промптов и конкретных действий модели не писать и
не восстанавливать; поведение проверяется ручным живым прогоном.
Подробные границы — [инструкции Agent Service](services/agent/AGENTS.md).

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
