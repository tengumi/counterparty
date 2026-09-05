# Next steps: запуск разработки через субагентов

**Текущая цель:** срез I — живые разделы отчёта/evidence и сравнение в UI,
read-only MCP и PostgreSQL checkpoint/restart. Пользователь поручил продолжить
после результата WEB-07; H и gate волны 1 приняты, WEB-07 отмечен done.

**Источник полного backlog:** [`docs/WORK_PLAN.md`](docs/WORK_PLAN.md).

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
| I1 / API-06 | in progress | `services/ui_api/**`, чистые общие read projections в `packages/domain/**`, ReportEvidence DTO в contracts; sections и project-scoped evidence |
| I2 / MCP-01/02 | in progress | `services/mcp/**`; authenticated read-only tools с pinned report, фильтрами и cursor |
| I3 / F0-07 | in progress | `services/agent/**`, `migrations/**`, минимальный AgentRun model/repo в storage workspace; штатный saver, scope и restart/interrupted proof |
| I4 / WEB-08 | waiting I1 | `apps/web/**`; REST overview/report/evidence/materials/comparison, без mock fallback |
| I5 / independent verification | waiting integration | независимые HTTP/MCP/restart проверки и один финальный browser flow |

I1–I3 стартуют параллельно от baseline `1173476`. Contracts/domain имеют только
writer I1; storage workspace/migrations — только I3, остальные storage файлы
read-only до конкретного запроса. I4 стартует после API-06, с отдельной веткой и
worktree; I5 проверяет общий срез независимо. UI baseline H сохраняется; новое
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
