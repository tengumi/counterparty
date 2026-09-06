# Next steps: запуск разработки через субагентов

**Текущая цель:** довести MVP по Specs одним консолидированным заходом. Волны
A–I приняты, J влит (`c1c356e`, `92f73a9`, `1ef8ddf`). Осталось закрыть AG-04,
недостающие REST-стыки, реально поднять Compose и провести сквозную приёмку.
Полный список — раздел «Остаток MVP» ниже.

## Как вести остаток — решение пользователя 06.09.2026

Ранние волны раздробили работу слишком мелко: ~10 волн по 3 параллельных
субагента, per-task checkpoint-файлы, верификатор почти на каждую волну,
обязательный user-checkpoint после каждой волны. На фактическое качество кода
(плоская раскладка `services/ui_api`) это не повлияло, а бюджет 5-часовых окон
сожгло на холодные старты агентов и бумагу между ними.

Остаток ведётся иначе (полные правила — в `AGENTS.md`):

- Главный агент делает работу сам, последовательно, без веера субагентов.
  Субагент — только если часть действительно независима и крупная; максимум два.
- Никаких новых `docs/checkpoints/tasks/*.md`. Запись — git history + этот файл.
- Не останавливаться на user-checkpoint между пунктами: пользователь разрешил
  непрерывное выполнение. Спрашивать только на настоящих развилках (неоднозначный
  смысл Specs, изменение объёма, необратимое действие).
- Независимый проверяющий — только на живой grounded-сценарий агента (AG-03/AG-04).
- `docs/Specs/` не менять: недостающие эндпоинты Specs 10 §5, AG-04 и OPS-01 там
  уже описаны, отстаёт только код.

Граница MVP прежняя: документы и follow-up (DOC-01…03, AG-05, WEB-10) — post-MVP.
Provider/model подключает пользователь; всё строится на deterministic adapter,
model ID не хардкодится. Готовность реальной модели не объявляется без прогона.

**Источник полного backlog:** [`docs/WORK_PLAN.md`](docs/WORK_PLAN.md).

## Уточнение пользователя — текущий заход 06.09.2026

- Продолжать самому, без исполнителей-субагентов.
- Сразу подключить DeepSeek V4 Flash (`deepseek-v4-flash`) через NeuralDeep;
  provider/model/base URL — конфиг, ключ из `.env`, только backend.
- После подключения модели перезапустить весь стек, выполнить живой прогон
  и завершить WEB-12 и приёмку. Готовность пока не подтверждена.

## Результаты текущего исправления — 06.09.2026

- Пользователь попросил исправить вход: добавлен SessionGate с явным демо-входом,
  восстановлением cookie-сессии и повторным входом при 401 без потери формы.
- Найдена причина «не работает»: UI отправлял `/rpc/agent/chat`, Compose proxy
  обслуживал только `/agent/…`; браузер получал 405. Добавлен штатный RPC route,
  SSE timeout 360s; Vite proxy исправлен на порт агента 8001.
- DeepSeek V4 Flash подключён штатным langchain-openai; backend получает ключ
  из `.env`, provider/model/base URL/max tokens настраиваются. Весь стек
  пересоздан с сохранением БД. 4096 токенов на ответ, 300s на run в локальном env.
- Прямой вызов модели: 1.5s. Сквозной run `e2908307-ddfb-462e-adb9-6233b7a9057f`
  завершился за 95s, история сохранена и читается через conversation API.
  При пересборке ui_api восстановилась выдача проекции (старый образ отставал).
- Живой ответ выявил разрыв сумм по точке перед ₽/RUB: splitter исправлен,
  добавлен regression test; prompt требует краткого ответа и исходных единиц.
- S2: оформлены карточки решения/AI-вывода, выровнена типографика, исправлена
  кнопка возврата к разговору. Браузерная матрица 390/1024/1440 пройдена: вход через UI,
  материалы/решение без горизонтального overflow, восстановление после reload.
  Скриншоты и checks.json — `.screenshots/web12/`.
- Проверки: web 102 passed с `--maxWorkers=2` (параллельно с Docker сборкой
  стандартный прогон упирался в 5s timeout); lint/typecheck/build зелёные.
  agent 76 passed, 14 PostgreSQL-тестов skipped; ruff/format/mypy зелёные.
  Docker agent/ui_api/web собраны, nginx config валиден.
- Пустая проверка теперь сразу предлагает добавить компанию, без обращения
  к модели/MCP; scoped precondition покрыт тестом.
- Независимая приёмка AG-04/AG-07 остаётся открытой: после замечания пользователя
  субагенты не запускаются. Полную готовность агентского UX не объявлять:
  поведение без закреплённой компании и длительность ответов требуют проверки.

## Текущее состояние

- Specs 1.1, архитектурная карта и подробный план готовы.
- Старый `src`-прототип и корневой Python/uv-проект удалены.
- Gate F0 и волны D/E приняты. Волна F принята пользователем 05.09.2026 и
  интегрирована в `dev` через merge-коммиты F1/F2/F3.
- G1–G4 интегрированы в `dev`; независимая проверка G5 и web/HTTP-проверка G6
  пройдены. Срезы G и H приняты 05.09.2026; начат I, первый срез волны 2.
- `packages/`, `migrations/`, `scripts/import_reports`, `apps/web` и три
  Python-сервиса в `services/` созданы; выполнены базовый storage/import,
  project/company API и web-отчёт по typed mocks.
- Docker build context для Python-сервисов — корень монорепы (`docker build -f
  services/<svc>/Dockerfile .`), иначе локальную зависимость
  `packages/contracts` собрать нельзя. Dockerfile остаются внутри сервисов.
- Каждый сервисный venv собирается сразу по финальному пути `/app/.venv`:
  перенос готового venv между путями ломает console scripts.
- Решение пользователя: `packages/domain` объявляет `counterparty-contracts`
  локальной зависимостью и переиспользует `Availability`, `EvidenceKind` и
  `EvidenceRef` вместо дублирования. Транзитивный pydantic в domain допустим —
  ограничение domain относится к I/O, а не к зависимостям.
- Решение пользователя: датовые поля источника хранятся как точный момент
  времени, а не как календарная дата — источник кодирует локальную полночь при
  разных смещениях UTC. Календарная дата вычисляется на слое отображения.
- Решение пользователя: `import_warnings`, `company_profiles.website`/
  `extra_jsonb` и `ordinal` приняты сверх исходных Specs §3 и внесены в
  `docs/Specs/02_DATA_AND_STORAGE.md`.
- Дизайнерский HTML принят как UI baseline и не должен редактироваться.
- Решение пользователя (волна F): повтор идемпотентного запроса отвечает `200`
  с заголовком `idempotent-replay: true`, а не `201`; клиент обязан различать
  «создано» и «это уже было». Внесено в `docs/Specs/10_SYSTEM_CONTRACTS.md` §5.
- Решение пользователя (волна F): предложения F2 по `packages/storage`
  принимаются и выносятся отдельной задачей волны G — фильтр владельца и
  `title_contains` в `ProjectRepository.list_recent`, `IdempotencyRepository.release`
  и политика зависших in-flight ключей, батч-чтение состава проверки вместо N+1,
  `CompanyReadRepository.search` по локальному индексу (нужен также MCP и агенту).
- Локальные пакеты ставятся в venv сервисов НЕ editable: сразу после merge
  изменений в `packages/**` тесты сервиса падают на устаревшей копии. Шаг
  интеграции — `uv sync --reinstall-package counterparty-contracts` (и storage,
  domain) в каждом затронутом сервисе.
- Mock JSON утверждён и используется напрямую из
  `artifacts/contractors_audit.snapshot.json`.
- Slim `compose.yaml` уже поднимает PostgreSQL, миграции, роли и импорт. Полный
  OPS-01 с `web`, `ui_api`, `agent`, `mcp`, reverse proxy и healthchecks остаётся
  задачей после живой сервисной интеграции.

Главный агент обновляет этот файл после каждой интегрированной волны. Субагенты
не меняют его без отдельного поручения.

## Правила проверки, заданные пользователем

- Браузерные прогоны и скриншоты через Chrome DevTools делаются **один раз в конце
  волны**, а не на каждом подходе: это дорого по токенам и на промежуточном шаге не
  требуется. Внутри подхода UI проверяется lint/typecheck/tests/build и
  component-тестами.
- Выравнивание UI с референсным макетом — **отдельная задача**, а не часть каждой
  web-задачи. Web-задачи делают поведение и структуру; сверка с
  `artifacts/Design TZ для экранов/Проверка контрагентов v2.dc.html` и правки
  внешнего вида идут одним заходом вместе с WEB-07.

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
| A1 / F0-01, F0-02, F0-05 | done | accepted; integrated through `1c6ffd7`; 23 contract tests, package quality/build checks pass |
| A2 / F0-04, WEB-01 | done | accepted; integrated through `624f4d2`; GPT-6 medium; 5 tests, lint/type/build/Docker smoke pass |
| A3 / IMP-01 audit | done | accepted; checkpoint-файл утерян — аудит воспроизведён в C2, контрольные значения и digests зафиксированы в `docs/checkpoints/tasks/C2.md` |

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
| B1 / F0-03A | done | accepted; integrated through `51b3931`; 2 tests, lint/type/build/container health pass |
| B2 / F0-03B, V04 spike | done | accepted; integrated through `bc752bf`; 4 tests; V04 частичный, migration proposal в `docs/checkpoints/tasks/B2.md` |
| B3 / F0-03C, V05 spike | done | accepted; integrated through `072777d`; 5 tests, stateless FastMCP HTTP подтверждён |

## Волна D — первый продуктовый подход (волна 1 плана)

Gate F0 пройден полностью. Узкое место волны 1 — `packages/contracts`: от
DTO зависят 12 из 21 задачи, а редактировать пакет одновременно может только
один агент. Поэтому первый подход отдаёт contracts одному владельцу целиком, а
два других слота занимает работой, которая от DTO действительно не зависит.

| Task | Статус | Исполнитель/результат |
|---|---|---|
| D1 / C-01, C-02 | done | accepted; 100 tests; зависимые пакеты не сломаны |
| D2 / WEB-02, WEB-03 | done | accepted; 27 web tests; скриншоты 1440/390 сняты |
| D3 / D-03 | done | accepted; 107 tests; расчёты grounded в evidence |

| Task | Статус | Исполнитель/результат |
|---|---|---|
| E1 / DB-03, DB-04 | done | integrated; 74 storage + 17 migration tests на живом PostgreSQL |
| E2 / WEB-04, WEB-05 | done | integrated; 51 web test, lint/typecheck/build зелёные |
| E3 / C-03, C-04, API-01 | done | integrated; 135 contract + 17 ui_api tests |

Итог волны E на `dev`: 420 тестов (contracts 135, domain 107, storage 74,
migrations 17, ui_api 17, agent 14, mcp 5, web 51). Прерывание волны на лимите
бюджета показало, что восстановление из task-ветки и checkpoint работает: обе
упавшие задачи подняты и доведены без пересказа истории чата.

Ограничения, унаследованные волной F:

- E1: привилегии на framework-owned checkpoint storage (LangGraph) не выдаются
  миграцией — их namespace создаёт владеющая библиотека на своём шаге деплоя.
- E1: тестам `packages/storage` и `migrations` нужны разные базы; сессионная
  фикстура storage пересоздаёт схемы и рассогласует чужой `alembic_version`.
- E2: `getConversation`, `getMaterials`, `findEvidence` — моки; границей замены
  на REST служит union `ConversationBlock`. Отправка живёт только в демо-чате,
  остальные в состоянии `unavailable`.
- E2: состояние `cancelling` недостижимо в чатах без живого треда; S2-уровневый
  тест terminal error/cancel опирается на end-to-end `chat/transport.test.tsx`
  из C1.

Решения по спорным именам из D1 (принято главным агентом, возражений не поступило):
`Proceeding.started_at` остаётся; `warnings[]` переводится в типизированный
`{code, message, source_path}` сейчас, пока ui_api на него не оперся.

Открытый стык после подхода D: composer разговора на S2 — это ещё spike-компонент
из C1 с двумя красными кнопками подряд, что нарушает правило одного primary CTA.
Владельца у стыка не было: C1 делал транспорт, D2 — рамку вокруг. Закрывается в
WEB-04, отдельная правка сейчас не нужна.

| Task | Статус | Исполнитель/результат |
|---|---|---|
| F1 / IMP-02, IMP-03, slim OPS-01 | done | integrated; 43 теста; 100 снапшотов импортированы под ролью importer, повтор ничего не меняет |
| F2 / API-02, API-03 | done | integrated; 41 тест, 24 на живом PostgreSQL; гонка идемпотентности проверена двумя потоками |
| F3 / WEB-06 | done | integrated; 62 web-теста; значение без основания не показывается |

Волна F принята пользователем 05.09.2026. Browser-прогон F3 намеренно не
выполнялся: единая проверка 390/1024/1440 остаётся на WEB-07.

Дефект downgrade ревизии `0004` исправлен в G3: миграция снимает grants своей
БД и не удаляет cluster-wide роли. G5 независимо подтвердил regression на двух
БД одного кластера.

Порядок дальнейших подходов волны 1 (уточняется после каждого review):

1. **D:** contracts C-01/C-02 · web S1/S2 · domain D-03 — принято.
2. **E:** DB-03 + DB-04 · WEB-04 + WEB-05 · C-03/C-04 + API-01 — сведено.
3. **F:** IMP-02 + IMP-03 + slim OPS-01 · API-02 + API-03 · WEB-06 — сведено. Здесь же slim `OPS-01`:
   Compose появляется, как только есть что поднимать целиком — PostgreSQL,
   миграции, импорт и сервисы.
4. **G:** API-04 + API-05 + D-04 · живой project/company CRUD в web ·
   storage wiring и безопасный downgrade — принято.
5. **Завершение волны 1:** WEB-07 вместе с выравниванием UI по референсному
   макету — отдельной задачей, тогда же единственный браузерный прогон и
   скриншоты 390/1024/1440.

### Волна G — принята

G1/G2/G3 влиты до текущего подхода; G4 завершил wiring, G5 независимо проверил
данные и API, G6 проверил web и живой HTTP flow. Полный WEB-08 не объявляется
выполненным: comparison/overview/materials ещё не подключены в UI, формальная
зависимость от WEB-07 остаётся.

| Task | Статус | Область и результат |
|---|---|---|
| G1 / D-04, API-04, API-05 | done | merged `f100723`; overview/comparison подтверждены PostgreSQL tests и HTTP smoke |
| G2 / live API slice | done | merged `1a9edf1`; живой CRUD проектов/компаний проверен, overview/materials/comparison остаются typed mocks; не полный WEB-08 |
| G3 / storage + migration debt | done | merged `8df63b9`; 80 storage + 18 migration tests, wiring завершён в G4 |
| G4 / API storage integration | done | implementation `37e1b25`, final `0bb8aaa`; repositories подключены, 50 API tests и независимый повтор прошли |
| G5 / data integration verification | done | независимый pass: 436 Python tests, 0 skipped; все локальные ruff/format/mypy checks прошли |
| G6 / web verification | done | 74 web tests, lint/typecheck/build; 17 HTTP checks и auth/projects через Vite proxy прошли; README и WEB-07 handoff готовы |

Всего в матрице G: 510 tests (contracts 135, domain 110, storage 80,
migrations 18, importer 43, ui_api 50, web 74). UI API отдельно перепроверен
независимым verifier. В целевом `services/ui_api/.venv` выполнены frozen sync,
переустановка contracts/domain/storage и import smoke.

05.09.2026 пользователь поручил продолжить после аудита; после прерывания работа
возобновлена с task-checkpoints. G4–G6 завершены без запуска новой крупной волны.
Подготовлены native Python/PostgreSQL и Node/npm; Docker отсутствует, образы и
Compose в этом подходе не запускались. Browser-проверка остаётся на WEB-07.

Результаты и воспроизведение: `docs/checkpoints/tasks/G4.md`, `G5.md`, `G6.md`;
пользовательские команды — `README.md`. Native demo содержит 100 исходных mock
snapshots и использует ограниченную UI API роль; тестовые БД отделены от demo.
Для русского поиска test/demo DB создана с Unicode-aware `LC_CTYPE`: исходный
локальный setup `C` давал ложный failure ILIKE, на корректной БД suite прошёл.
G4 намеренно не перехватывает in-flight по возрасту; без reconciliation/fencing
такой takeover способен создать дубликат. Completed idempotency key сохраняется
даже при ошибке после успешно выполненного commit.

### Срез H: WEB-07 — принят

- Выравнивание S1/S2 с неизменяемым дизайнерским HTML; один браузерный прогон и
  screenshots 390/1024/1440, включая материалы/report/evidence и состояния ошибок.
- Полный визуальный S2 проверять через browser-test harness/intercept с уже
  существующими typed fixtures; реальные REST UUID пока не связаны с mock content.
  Отдельно проверить live CRUD с demo session. Не добавлять production fallback
  или искусственные report IDs в БД ради скриншотов.
- Ownership: `apps/web/**` и отдельный task-checkpoint. Подробный handoff — G6.
  WEB-08/09 и полноценный агентный сценарий в этот визуальный срез не включать.
- 05.09.2026 пользователь поручил продолжить по плану после checkpoint G;
  D-04/API-04/API-05 отмечены done в WORK_PLAN. Замечаний к G не добавлено.

| Task | Статус | Ownership / результат |
|---|---|---|
| H1 / WEB-07 UI alignment | done | S1/S2, адаптивные материалы/report/evidence, draft/scroll/focus; исправления итоговой проверки интегрированы |
| H2 / WEB-07 browser harness | done | Chrome/CDP harness, 34 PNG с provenance, fixtures и отдельный live CRUD; точечные повторы прошли |
| H3 / independent WEB-07 review | done | независимый source/PNG/manifest review: pass with limitations, открытых WEB-07 blockers нет |

H1 и H2 реализуются параллельно от одного baseline; финальный браузерный прогон
Chrome DevTools/CDP выполняется после объединения. H3 сверяет итог с Specs/HTML.
До финального прогона — lint/typecheck/component tests/build без промежуточных
скриншотов. Найденные при финальной проверке дефекты исправляются с точечным
повтором затронутых сценариев. После H — пользовательский checkpoint; WEB-08
или агентная волна автоматически не запускаются.

Итог H от 05.09.2026:

- Интегрированный код: `6942d5a`; lint/typecheck/qa:check/build прошли,
  77 component/unit tests прошли. После последних CSS-правок повторены
  lint/qa:check/build и затронутые браузерные сценарии.
- Первый итоговый capture `b13cc17`: 27 PNG и 94 checks (90 pass / 4 fail),
  live CRUD прошёл, consoleErrors пуст. Найденный tablet overlay шириной 1 px
  исправлен; два ложных source-state failures исправлены scoped selectors.
  Независимый review также нашёл и исправил desktop Enter hint на mobile.
- Точечные captures `6942d5a`: tablet S2/panel/report/evidence — 26/26;
  mobile/desktop availability и mobile hint — 13/13, ещё 7 PNG.
  Оба процесса завершились успешно, consoleErrors пуст. Исходные captures
  сохранены с прежним SHA; новые находятся в `follow-up/`.
- Результат и снимки: `artifacts/qa/WEB-07/README.md`; воспроизведение:
  `apps/web/qa/README.md`, live API/UI — корневой README. Task-checkpoints H1–H3
  содержат реализацию и независимую проверку. Branches/worktrees сохранены.
- Ограничения: 200% — эмуляция размера текста на S1, native zoom/экранная
  клавиатура не проверялись. Полные отчёт/разговор/материалы показаны на typed
  fixtures, live CRUD — через PostgreSQL/REST. WEB-08/09, документы и полноценный
  агентный сценарий не входят в этот gate. Docker в окружении отсутствует;
  Dockerfile в H не менялись. Известное предупреждение о размере bundle остаётся.

Пользователь принял H поручением «Продолжай по плану»; замечаний к H не добавлено.

### Текущий срез I: REST/MCP/persistence

Демонстрируемый результат: открыть импортированный отчёт и основание в живом
REST UI, сравнить закреплённые отчёты; получить те же исходные факты через
стандартный MCP; независимо доказать PostgreSQL checkpoint/restart. Полный
grounded агентный разговор, upload и сохранение решения остаются последующими
задачами AG/DOC/WEB-09/11.

Обнаруженная зависимость: Specs 10 §5 содержит report sections и project
evidence REST, но в API-01…05 они не входили и ещё не реализованы. В WORK_PLAN
добавлен API-06 как prerequisite WEB-08; Specs и границы сервисов не меняются.

| Task | Статус | Ownership / результат |
|---|---|---|
| I1 / API-06 | ready for review | REST sections/evidence, shared projections и repository bundle; 100×17 разделов, 14035 refs; независимые HTTP-проверки пройдены |
| I2 / MCP-01/02 | ready for review | authenticated read-only tools; независимо 31 tests, 5555 refs, parity 100 overviews/96 pages; Docker build не проверен |
| I3 / F0-07 | ready for review | native saver в workspace, AgentRun и restart; исправление I7 независимо подтверждено; Docker build не проверен |
| I4 / WEB-08 report slice | ready for review | live report/evidence/comparison; 92 web tests, lint/typecheck/build; 53 browser checks passed, final touch targets/favicon replay passed |
| I5 / API-agent verification | passed with limitations | `eff2c64`; baseline 441, targeted agent22/storage83/migrations19/domain122, 21 HTTP checks, fencing и framework roundtrip |
| I6 / MCP-web verification | passed with limitations | `b08abe6`; MCP31, parity100 overviews/96 pages; browser53/53, 14 reviewed PNG, mobile44px, favicon200, console clean |
| I7 / checkpoint write fencing | ready for review | `6377532`; saver использует owner connection, stale graph/aput/aput_writes/delete отвергнуты; I5 подтвердил продолжение новым процессом |

I1–I3 стартуют параллельно от baseline `1173476`. Contracts/domain и storage
`repositories/reports.py` имеют только writer I1; storage workspace/migrations —
только I3, остальные storage файлы read-only до конкретного запроса. I4 стартует после API-06, с отдельной веткой и
worktree; I5/I6 проверяют чужую реализацию независимо. UI baseline H сохраняется; новое
визуальное выравнивание не требуется. Browser/screenshots — только в конце I.
Root обновляет статусы здесь; WORK_PLAN done — после пользовательского review I.

Интеграционные решения discovery I:

- Уточнён недостающий ReportEvidence response в Specs10: разрешённая ссылка,
  identity снимка, availability, исходный JSON-фрагмент и warnings. I1 реализует
  DTO и проверки; scope только report_field, документные/derived источники позже.
- I1 выносит pure read projections в domain, I2 использует их с reports-only
  adapter; MCP не импортирует UI API. Пагинация обозначает truncation существующим
  `result_truncated` warning и `PageInfo`, без дополнительного протокола.
- MCP использует штатную token verification с `reports:read`, серверный digest
  токена и fail-closed config. Секреты не попадают во frontend/логи.
- Для F0-07 нужен минимальный durable AgentRun в storage. Recovery обязан
  различать restart и живой соседний worker; ограничения spike должны быть
  принудительно проверяемыми. Полная run registry/projection остаётся AG-04.
- Review API/MCP: batch SQL чтения вынесен в задачу I1 storage repository bundle,
  сервисы собирают domain input из загруженного bundle; I3 добавляет scoped
  historical-report membership method для evidence. Сервисные SQL queries не
  подменяют слой repositories. При этом storage не зависит от domain.
- I1–I3 сведены в `4dee1b2`; независимая проверка выполняется в отдельных I5/I6
  worktrees. I4 использует API pins и серверные DTO. Comparison без persisted id
  остаётся локально открытым результатом, не объявляется сохранённым artifact.
- Реальные проекты не получают mock terms/documents/analysis/decisions:
  соответствующие будущие API/DOC/AG возможности показываются как unavailable.
  В I проверяется живая отчётная часть материалов; это не полный gate волны 2.
- Независимый I5 обнаружил stale checkpoint write после потери owner connection.
  I7 исправил границу записи: штатный saver работает на той же физической
  connection, что и owner lock. Повтор I5 отвергает все старые пути записи,
  сохраняет исходный CheckpointTuple и подтверждает продолжение новым процессом.
  Один worker на БД обязателен; protected `_cursor` hook привязан к locked
  langgraph-checkpoint-postgres 3.1.2. Runtime RPC остаётся in-memory до AG-04.
- I4 исправил потерю периода финансового evidence, включая дополнительные поля
  старых лет вне overview. Domain122 и независимые 21 HTTP-проверка прошли.
- Demo PostgreSQL мигрирован до 0005; штатные checkpoint tables развёрнуты
  отдельной deploy-командой. Live browser на `2dce684`: 53 assertions прошли,
  13 screenshots, все 24 API-ответа без HTTP-ошибок. Единственный console404
  оказался отсутствующим favicon; визуальная проверка нашла mobile context
  buttons меньше 44px. I4 исправил оба; финальный адресный replay на `0c20738`
  подтвердил 44px, favicon200, отсутствие overflow и ошибок console/page.
  Исходные manifests сохранены отдельно, повтор полного flow не требуется.

### Срез I принят 05.09.2026

Пользователь смотрел живой запуск (PostgreSQL 55432, ui_api 8000, web 5173) и
дал команду продолжать. В WORK_PLAN отмечены `done`: API-06, MCP-01, MCP-02,
F0-07 и WEB-08. Для WEB-08 сохранена граница: живая отчётная часть материалов и
сравнение реализованы, terms/documents/analysis/decision API отсутствуют и
показываются как unavailable.

Подтверждено на живом запуске: ранее записанная проблема non-editable пакетов
(см. «Текущее состояние») ломает не только тесты, но и старт сервиса — ui_api не
поднялся с `ImportError: ReportEvidence`. Постоянное решение выбирает OPS-01.

## Остаток MVP — один заход

J влит. Что дал каждый срез и его известная дыра:

- **J1 (AG-01/02/03)** — harness агента, детерминированный, evidence-граница под
  тестом (32 теста). Дыра: RPC не несёт tenant scope, `harness/runner.py`
  использует тонкие `default_context`/`default_config`. Точки инъекции готовы:
  `WorkspaceContextSource`, `checkpointing.checkpoint_config`.
- **J2 (MCP-03 + OPS-01)** — `compare_companies` + parity-тест по HTTP готовы.
  `compose.yaml` со всеми 4 сервисами + proxy + checkpoints-job написан;
  `docker compose config` и build проходят, **полный startup ни разу не поднят**.
- **J3 (WEB-09/11)** — транспорт подключён к живому пути, форма решения есть; при
  отсутствии серверных эндпоинтов UI честно деградирует и не сохраняет локально.

Порядок работы (последовательно, главным агентом):

1. **UI API эндпоинты Specs 10 §5** — ✅ сделано 06.09.2026. Добавлены
   `GET/POST /projects/{p}/decisions`, `GET /projects/{p}/artifacts`,
   `GET /projects/{p}/threads/{t}/conversation`.
   - Миграция `0006`: `workspace.user_decisions` (версионирование через
     `supersedes_id`, автор — `RESTRICT` FK на `users`, никогда не
     перезаписывается) и `workspace.analysis_artifacts` (immutable по
     `(id, version)`). Обе привязаны к проекту по `(id, tenant_id)`; ui_api
     получает доступ через whole-schema default privileges из `0004`.
   - Storage: `UserDecisionRepository`, `AnalysisArtifactRepository`,
     read-only `AgentRunReadRepository` в `AsyncUnitOfWork`
     (`uow.decisions/artifacts/agent_runs`). `created_at` этих таблиц —
     `clock_timestamp()`, чтобы записи одной транзакции сохраняли порядок.
   - Contracts: новые `AnalysisArtifact` + `ArtifactGround`,
     `ThreadConversationState` (= `PublicAgentState` + `active_run_id`).
   - Conversation endpoint не держит третью копию conversation state:
     messages/activities пусты (проекция принадлежит agent service), а `run`/
     `active_run_id` читаются из `agent_runs` как reconnect-цель. Полную
     проекцию наполнит AG-04.
   - Границы: decision цитирует artifact-версию только если она есть в проекте
     (иначе 404); `context_version` в теле — записывается, не guard;
     `workflow_status` проекта не трогается. Проверки: contracts 144,
     storage 88, migrations 19, ui_api 70 — все зелёные на живом PostgreSQL.
2. **AG-04** — ✅ сделано 06.09.2026. Run lifecycle пережил и процесс, и рестарт.
   - `transport/durable.py::DurableRuns` — зеркалит lifecycle
     (`accepted → running → cancelling → terminal`) в `workspace.agent_runs`
     через единственный fenced `AgentRunOwner` (та же физическая connection,
     что и owner lock; ограничения I7 не нарушены — saver не трогали).
   - `RunRegistry` получил опциональный `durable`: `start()` теперь async и
     сперва пишет acceptance — её отказ (на треде уже есть активный run,
     partial unique index) поднимается как `409`. Терминальный статус
     зеркалится **до** закрытия стрима, чтобы читатель ответа видел
     осевшую строку. In-memory лог событий по-прежнему не персистится
     (Specs 10 §7: воспроизведение токенов не требуется).
   - Storage: `AgentRunOwner.resolve_thread_scope()` (доверенный
     `(tenant, project, thread)` из строки проекта — у RPC нет сессии) и
     `find_run()` (чтение по id для чужого/после-рестартного run).
   - RPC: `/chat` резолвит scope и отвергает нерезолвимый project/thread
     (`404`); `/runs/{id}`, `/subscribe`, `/cancel` при отсутствии run в
     памяти читают durable строку — `interrupted` после рестарта не
     показывается вечно running, `/subscribe` отдаёт одну проекцию.
   - Recovery на старте/выключении — существующий `postgres_run_owner`
     (`interrupt_active`), не трогал.
   - Проверки: agent 66 (5 новых durable-тестов на изолированной
     PostgreSQL + non-owner runtime login), storage 88, ui_api 70, mcp 32 —
     зелёные. Независимый проверяющий по плану ещё нужен.
3. **Проброс tenant scope в RPC агента** — ✅ сделано 06.09.2026.
   - `Run`/`RunContext` несут резолвнутый `ThreadScope`; `RunRegistry.start`
     проставляет его. `harness/runner.py` берёт `ctx.scope` (или тонкий
     fallback `tenant=0` для процесса без БД) и передаёт в загрузчики.
   - `default_context`/`default_config` теперь принимают `ThreadScope`.
   - Композиция: при наличии DSN поднимается небольшой read-only
     `session_factory` (pool 2); `select_runner` подключает
     `WorkspaceContextSource(session_factory).load` и
     `partial(checkpoint_config, owner)` — авторизованные слои проекта/треда
     и checkpoint-ключ по server-verified треду, не по значению из запроса.
   - Проверки: agent 68 (2 новых: runner передаёт scope в загрузчики; RPC
     резолвит доверенный scope из проекта и отвергает чужой тред).
4. **OPS-01 до конца** — ✅ сделано 06.09.2026. Docker в окружении есть (28.1.1).
   - `docker compose build` (все 5 образов) + `up -d`: `migrate` накатил `0006`,
     `roles`/`import`/`checkpoints` отработали как one-shot, все 6
     долгоживущих сервисов `healthy` (postgres, ui_api, agent, mcp, web,
     proxy). Компоуз-файл не менялся — поднялся as-is.
   - Ручной проход через proxy (`localhost:5173`): auth → создание проекта →
     новые `GET /decisions|/artifacts|/threads/{t}/conversation` (200, пусто) →
     `POST /decisions` (201) → `POST /agent/rpc/agent/chat` (harness+MCP путь)
     завершился `completed`, строка в `workspace.agent_runs` осела
     (`status=completed`, `last_public_revision=2`), checkpoint записался под
     ключом `uuid5(tenant:project:thread)` — item 3 подтверждён на живом
     стеке. Нерезолвимый тред → `404`. Смоук-проект вычищен.
   - Известное: `GET /rpc/agent/runs/{id}` для ещё живущего в памяти run
     отдаёт `finished_at:null`/`revision:0` (in-memory `_run_info` копирует
     только статус) — pre-existing, durable строка корректна.
5. **Сквозная приёмка** — ✅ сделано 06.09.2026 на контейнерном стеке.
   Компания А = ООО «СПОРТ» (ИНН 9705152496). web/proxy → ui_api (auth →
   проверка → контрагент по ИНН, ctx v1) → agent RPC → mcp → grounded-ответ:
   18 финансовых строк 2023-2025, каждая с разрешимой
   `[evidence:report:<snapshot>:/finReports/…]`, блок «Неизвестно» с
   отсутствующими разделами; run осел в `agent_runs` (`completed`); решение
   `ready_with_conditions` с двумя условиями и evidence_refs записано (201);
   `…/conversation` показал `run:completed, active_run_id:null`.
   - Живой прогон вскрыл интеграционный баг: LangChain MCP-адаптер отдаёт
     tool-result как content-blocks `[{"type":"text","text":"<json>"}]`, а
     детерминированный адаптер и evidence-ledger ждали JSON-строку → ВСЕ
     grounded-строки отбрасывались как unreferenced и ответ был пустым.
     Починено в `harness/deterministic.py::_payload` и
     `harness/evidence.py::_as_json` (+2 регресс-теста). agent 70.
   - Runbook: `docs/DEMO_RUNBOOK.md` (поднять стек, пройти сценарий, проверить
     живучесть run'а, границы каркаса, свернуть).
   - Независимый проверяющий на живой прогон п. 5 по плану ещё нужен.
6. **Рефакторинг раскладки `services/ui_api`** — ✅ сделано 06.09.2026,
   отдельным коммитом, только `git mv` + правка импортов.
   - `routes/` — 8 роутеров (auth, health, projects, companies, reports,
     report_details, decisions, conversation) + `__init__` с реэкспортом;
   - `reads/` — `models.py` (бывш. `reads.py`) + `views.py`, `__init__`
     реэкспортит мапперы и read-модели;
   - `loaders/` — `reports.py` (бывш. `report_loader.py`);
   - плоско остались 11 инфраструктурных модулей (`app`, `config`,
     `database`, `dependencies`, `errors`, `sessions`, `provisioning`,
     `idempotency`, `cursors`, `workspace`, `__init__`).
   - 70 тестов зелёные без изменений, mypy/ruff чистые, образ пересобран,
     контейнер `healthy`. `report_*` в `packages/domain` не выносил — по
     желанию, отдельно.
7. **Сверка UI с макетом + персист истории диалога** — 7b сделано 06.09.2026,
   7a — заход 06.09.2026 (осталась только серия скриншотов 390/1024/1440).
   - **7a. UI ↔ `Проверка контрагентов v2.dc.html`.** — сделано 06.09.2026.
     - Внешний вид S2-панели решения/вывода (`DecisionPanel`, `Conclusion` =
       AnalysisMemo, `RecordedDecision`, ResumeCard, materials-drawer) выровнен
       по неизменяемому HTML: `.panelHeader` gap/инсет, in-body заголовки
       14/20/500, карточка вывода — вопрос 16/24/500 + резюме 15/22, буллеты
       через приглушённое тире вместо disc, `.decisionHint` 12/16.
     - **Ответ помощника рендерился сырым Markdown** (`## Вывод`, `**…**`, `-`).
       `react-markdown` (прямая зависимость) → `MessagePrimitive.Parts
       components={{ Text: MarkdownText }}` в `AgentChat`; заголовки гасятся до
       жирного текста, списки — тире-буллеты, raw HTML отключён. Покрывает и
       live-, и восстановленную проекцию.
     - **Отчёт/сравнение вынесены из боковой панели 400px в полноэкранный
       `ReportScreen`** (макет `pReport`): верхняя полоса «← К разговору · Отчёт ·
       Компания/Сравнение», колонка `max-width:1080`, `LiveCompanyReport` /
       `Comparison` без изменений логики; основание открывается drawer-ом поверх.
       Открывается из strip'а (клик по компании / «Сравнить») только для живых
       проектов; демо сохраняет скриптовую панель. Панель осталась для
       list/terms/docs/evidence/document/decision.
     - **Сырые `[evidence:report:<id>:/path]` токены в ответе** → маленькие
       синие пронумерованные чипы «Основание N». `MarkdownText` вырезает токены
       по regex, нумерует по уникальному ref (одинаковый ref → один номер),
       рендерит `styles.evidence`-чип; клик открывает основание в панели.
       `onOpenEvidence` проброшен `ChatSurface → ProjectChat/AgentChat →
       EvidenceRefContext` (`evidenceContext.ts`). 3 unit-теста
       `MarkdownText.test.tsx`. Без opener'а — инертный `<sup>`.
     - Мелкие правки отрисовки: `LiveEvidence` группирует разряды числа
       (`-23 349 000`); дубль заголовка раздела в отчёте убран (h5 не рисуется,
       если совпадает с заголовком группы); заголовки колонок сравнения
       `proceedings`/`arbitration` → «Взыскания»/«Суды».
     - Демо-БД: 14 тестовых проектов soft-delete (`deleted_at`), список пуст.
     - Проверки: web lint/typecheck зелёные, `vitest run` 105 passed
       (обновлены 2 теста `liveReports.test.tsx` + 3 новых), build зелёный
       (bundle +~38 KB gz за счёт react-markdown). Живой прогон ООО «СПОРТ»
       через DeepSeek: 3 grounded-ответа с чипами, клик чипа → основание,
       консоль чистая. Осталось: единая серия скриншотов 390/1024/1440.
   - **7c. Персист истории диалога через несколько прогонов — TODO (backend).**
     Обнаружено на живом прогоне: `GET …/threads/{t}/conversation` отдаёт
     `messages` только последнего `agent_runs.public_projection` (2 сообщения,
     причём text-parts в blob'е пустые — UI дорисовывает последний ответ из
     памяти транспорта). При reload и после каждого нового send видно только
     последний обмен, предыдущие туры пропадают.
   - **7c. История диалога через несколько прогонов + наблюдаемый агент.** —
     ✅ сделано 06.09.2026 (`37fdb42`, `b37d7fe`, `c70a973`).
     - Прогон сидит свой `initial_state` предыдущей сохранённой проекцией треда
       (`AgentRunOwner.latest_projection`); фолд событий этого прогона поверх
       неё — и в стриме, и в осевшей проекции — даёт весь тред. Индексы
       message/activity в `harness/runner.py` и `stub_agent.py` считаются от
       длины сида, а не фиксированные 1/0, чтобы новый тур лёг после истории.
     - `ui_api`: conversation-эндпоинт берёт новейший прогон с проекцией
       (с откатом мимо ещё работающего), `as_thread_conversation` рендерит его;
       lifecycle по-прежнему из авторитетной строки.
     - `storage`: `AgentRunOwner.latest_projection` +
       `AgentRunReadRepository.latest_projection_for_thread`.
     - Наблюдаемость: чистое одношаговое завершение больше не рисует блок
       «Ход проверки» и строку «Ответ готов» — ответ говорит сам за себя;
       трейл остаётся для running/failed и для многошаговых прогонов (≥2 шага).
     - S1→S2: задача из S1 отправляется автоматически один раз
       (`AgentChat.AutoSend`, гард в state `ChatSurface`), без второго клика и
       без баннера «Текст перенесён». Живой прогон: один send = один run.
     - Composer: подавлен глобальный `:focus-visible` ring внутри поля (S1 Core
       + S2 textarea) — одна рамка-карточка, не две.
     - Проверки: agent 77, web vitest 106, lint/typecheck/build зелёные;
       storage/ui_api PostgreSQL-suite гоняются в контейнере.
   - Не сделано и намеренно оставлено на потом: metric-cards grid и year-column
     раскладка финансов из `pReport` (крупная переразметка `LiveCompanyReport`);
     i18n `case_status_raw` («Истец · Appealed»).
   - **7d. Наблюдаемый агент + разговорный промпт + добавление компании по ИНН.** —
     ✅ сделано 06.09.2026. Решения пользователя этого захода: отчёт по макету
     `pReport` — следующим срезом; агента выводить в разговорный, но без рефактора
     по ТЗ (ТЗ — продуктовый ориентир сценариев, не реализация); агент сам
     вызывает тул добавления ИНН.
     - **Стриминг действий.** `harness/middleware.py::ActivityTraceMiddleware` +
       `ToolTrace` — одна running→completed активность на каждый вызов тула;
       `graph.create_harness(trace=…)`; `runner._ActivityStream` считает индексы
       от длины сида. Пред-сид единственной активности «Читаю закреплённый отчёт»
       убран: трейл — это реальные вызовы, ход без тулов активностей не рисует.
       Карта `TOOL_ACTIVITY` (имя тула → kind + русский лейбл). `evidence_refs`
       осадка вешаются на первую активность прогона. Живой прогон: 7 активностей
       («Добавляю компанию…», «Открываю карточку…», «Читаю раздел…» ×5) осели в
       проекции.
     - **Пульс кружка.** `@keyframes dotPulse` + `.dot[data-status='running']`
       в `Conversation.module.css`, с `prefers-reduced-motion`.
     - **«Проверка завершена» убрана.** `AgentChat.LiveActivity` при чистом
       завершении возвращает `null` — трейл только пока идёт прогон или при сбое.
     - **Разговорный промпт.** `POLICY` переписан: идентичность (помощник
       Альфа-Бизнеса, зачем существует — прочитать готовый отчёт за
       предпринимателя), с чем помогает / чего не делает, тип сообщения
       (болтовня ≠ сделка, не тянуть старые суммы/проценты, не переспрашивать),
       живой русский без англицизмов, без Markdown-разметки, формат ответа,
       короткий словарь полей. Контекст из `artifacts/case.md` +
       `docs/Product_context_pack`.
     - **Светофор и ЗСК — определения от пользователя (06.09.2026).** Светофор:
       индикатор скоринга банка, методика внутренняя; зелёный надёжный / жёлтый
       внимание / красный риск / серый нет данных. ЗСК: платформа Банка России
       «Знай своего клиента», уровень риска подозрительных операций — низкий /
       средний / высокий; высокий = небезопасно по антиотмывочному закону.
       `knowledge.py` записи `bank_traffic_light` и `zsk_vs_bank_risk` обновлены,
       `REFERENCE_VERSION` 1 → 2 (заменяет прежнее «ЗСК только зелёный/серый»,
       F21 в `01_EVIDENCE_REGISTER.md` устарел).
     - **Добавление компании по ИНН.** Роль `counterparty_agent` не пишет
       `workspace` — новый session-less эндпоинт ui_api
       `POST /api/v1/internal/projects/{id}/companies` (заголовок
       `X-Internal-Token`, тенант из строки проекта), переиспользует
       `provision_one_by_inn` (индекс по ИНН → снимок → `project_companies.add`
       → bump `context_version`). Агент: `config.ui_api_url` +
       `ui_api_internal_token`, `harness/provisioning.py::build_add_company_tool`
       (локальный LangChain-тул `add_company_to_check`, httpx-POST, деградирует
       в сообщение). `compose.yaml`: `UI_API_INTERNAL_TOKEN` /
       `AGENT_UI_API_INTERNAL_TOKEN` (локальный дефолт). Пустая проверка без ИНН
       по-прежнему быстрым путём просит ИНН без модели; с ИНН — модель добавляет
       сама. Живой прогон: пустой проект → «аванс поставщику с ИНН 9705152496» →
       агент добавил ООО «СПОРТ» и ответил grounded; follow-up «а какая выручка?»
       — без повторного вопроса про ИНН.
     - Известное ограничение: DeepSeek V4 Flash держит формат нестрого — местами
       год-за-годом отдельными строками и ссылка в начале строки; дальнейшая
       настройка промпта модели — отдельно, вне этого захода.
     - Проверки: agent ruff/format/mypy + 84 passed / 14 skipped; ui_api
       ruff/format/mypy + 78 passed (в т.ч. 6 новых `test_internal.py` на живом
       PostgreSQL), 1 pre-existing fail
       `test_history_survives_while_the_next_run_is_still_working` (из 7c, не
       трогал); web lint/typecheck + 107 vitest + build зелёные.
     - Постороннее в worktree, не трогал: `docs/SUBAGENT_GUIDE.md` помечен
       удалённым (не этим заходом).
   - **7b. Durable публичная проекция разговора (AG-07).** — ✅ сделано
     06.09.2026.
     - Миграция `0007`: nullable JSONB `workspace.agent_runs.public_projection`
       (колонка наследует grants таблицы из `0005`/`0004`; отдельная таблица не
       понадобилась).
     - Агент: `transport/projection.py::fold_projection` сворачивает
       in-memory event-log (`Run.events`) в `PublicAgentState` — non-streaming
       двойник `delivery._deliver`. `RunRegistry._settle` вызывает его на
       терминальном переходе (успех и `FAILED`), `DurableRuns.finalize`
       пишет blob через `AgentRunRepository.set_status(..., projection=...)` на
       той же fenced owner-connection (граница I7 не тронута; saver не менялся).
       Фолд обёрнут в try/except → при сбое деградирует к обычному
       `advance`-mirror.
     - ui_api: `reads/views.py::as_thread_conversation` читает
       `run.public_projection` своим `AgentRunReadRepository` (в отличие от
       исходного плана — **без** нового HTTP-стыка ui_api→agent и RPC-эндпоинта
       агента; репозиторный доступ к `workspace` уже штатный для ui_api).
       Нечитаемый текущим контрактом blob → пустая история, не 500.
       `run`/`active_run_id`/`revision`/`context_version` по-прежнему из
       авторитетных строк, не из blob'а.
     - Проверки: storage 88, agent 74 (+4: fold happy/partial/delta, durable
       persist), ui_api 72 (+2: история из blob, деградация нечитаемого),
       migrations 19 — зелёные на живом PostgreSQL. Живой прогон компании А
       через proxy: `…/conversation` отдал полную grounded-историю
       (18 evidence-строк + блок «Неизвестно» + `activities` с refs,
       `save_status:saved`, `active_run_id:null`). Снят пункт §4
       `docs/DEMO_RUNBOOK.md`.

Независимый проверяющий — только на п. 2 и живой прогон п. 5.

## Итог захода 06.09.2026

Пункты 1–6 «Остаток MVP» закрыты и закоммичены в `dev`:
`d3c8945` (эндпоинты §5), `0b13bad` (AG-04), `294b7bd` (tenant scope в RPC),
`39cf37d` (OPS-01 bring-up), `19fc450` (MCP content-blocks fix + runbook),
`eb944a3` (рефакторинг раскладки). Стек поднят на текущем коде, миграция
`0006`, сквозной сценарий компании А отработал с grounded-evidence.

Пункт 7b (durable проекция разговора, AG-07) закрыт заходом 06.09.2026 —
миграция `0007`, агент фолдит и персистит финальный `PublicAgentState`,
ui_api отдаёт его из `agent_runs.public_projection`. Открытым остаётся
только 7a (сверка S2-компонентов с макетом + один браузерный прогон).

**AG-06 втянут в MVP-фазу** (06.09.2026, по просьбе пользователя — самое
дешёвое из post-MVP, backend-only, до web). `harness/knowledge.py`:
9 версионированных записей справочника Specs 04 §6 (source + worked-пример
каждая), детерминированный `lookup()` по topics без vector search,
`DOMAIN_NOTES` генерится из справочника, релевантные фрагменты подмешиваются
в system prompt через `runner`. agent 87 (+13), ruff/mypy чистые.

Осталось по плану: независимая проверка AG-04 и живого прогона приёмки;
дожимание агентского сценария и UI/UX, подключение реальной модели —
за пользователем. Post-MVP: AG-05, DOC-01…03, WEB-10, QA-01…05,
полный REL-01.

**Вне этого захода** (отдельная сессия после каркаса): QA-04 (агентные evals,
переподчинена AG-04 и AG-06). Заведена в WORK_PLAN. Пользователь берёт на себя
дожимание агентского сценария и UI/UX после MVP-каркаса.

Уточнение по harness: Deep Agents — harness, LangGraph — состояние и исполнение,
LangChain — провайдеры моделей. Собственный agent loop и роутер вызова
инструментов не пишутся (Specs 01 §32, Specs 08).

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
| C1 / F0-06, V01 | done | accepted; integrated through `76a61ee`; 14 backend + 11 web tests; V01 подтверждён на обеих сторонах |
| C2 / DB-01, DB-02, IMP-01 | done | accepted; integrated through `2df5629`; 59 tests; upgrade/downgrade проверены на реальном PostgreSQL |
| C3 / D-01, D-02 | done | accepted; integrated through `8986a0c`; 58 tests; валидаторы прогнаны по всему mock JSON |

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

Состояние на момент принятия волны B: пункты выполнены, кроме V01 (задача C1) и
полного V04. V04 подтверждён частично — проверена граница lifecycle
checkpointer'а; restart-поведение run зависит от схемы БД и модели run lifecycle
и переносится в задачу после DB-01. V05 подтверждён тестами `services/mcp`.

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
