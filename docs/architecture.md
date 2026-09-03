# Архитектура агента проверки контрагентов

**Статус:** предлагаемое решение, до начала реализации  
**Дата:** 3 сентября 2026  
**Область:** backend агента, данные, память сессии, API и тестовый UI-контур

## 1. Решение в одном абзаце

В качестве основного runtime используем **явный `LangGraph StateGraph`**. Из
SuperVisor переиспользуем инженерную оболочку: `uv`, `src`-layout, typed
settings, единую model factory, dependency injection, FastAPI, AG-UI/SSE,
checkpointer, трассировку, моки и слоистые тесты. `Deep Agents` в MVP не
подключаем; `PydanticAI` как второй agent runtime также не смешиваем с
LangGraph. Все вычисления, сопоставление компаний, построение похожей группы,
риск-правила и проверка доказательств выполняются обычным Python-кодом. LLM
нужна только для разбора действительно неоднозначного запроса и для
формулирования ответа по уже рассчитанным фактам.

Важно: `Deep Agents` и `LangGraph` — не взаимоисключающие аналоги. Deep Agents
является более высокоуровневым harness поверх LangGraph. Выбор здесь — на каком
уровне абстракции строить продукт.

## 2. Почему это подходит задаче

Процесс проверки заранее известен: идентификация компании, тематические
проверки, сравнение, следующий шаг и фиксация доказательств. Это управляемый
workflow с несколькими ветками, а не открытое исследование, маршрут которого
модель должна каждый раз придумывать заново.

| Вариант | Где силён | Решение для MVP |
|---|---|---|
| **LangGraph** | Явное состояние, ветвления, map/reduce, streaming, checkpoint и воспроизводимые маршруты | **Берём как ядро** |
| **Deep Agents** | Длинные открытые задачи, свободное планирование, filesystem, context offloading и динамические subagents | Не берём; большая часть возможностей не нужна и увеличивает latency и недетерминированность |
| **PydanticAI** | Компактный типизированный single-agent, structured output, DI и evals | Хорошая альтернатива для простого чата, но здесь потребует заново построить workflow и интеграцию с референсом |
| **Haystack / RAG-стек** | Большой корпус неструктурированных документов и retrieval | Сейчас не нужен: исходные данные структурированы |
| **Обычный Python** | Проверяемые правила, расчёты, поиск, сортировка и валидация | Используем внутри узлов графа как предметное ядро |

Выбор LangGraph не закрывает путь к Deep Agents. Позже его можно добавить как
один ограниченный узел для исследования длинных неструктурированных документов
или внешних источников, если evals докажут пользу.

## 3. Что диктуют выданные snapshots

Данные представлены двумя отдельными наборами по 100 компаний:

- JSON — вложенный snapshot размером около 2,4 МБ;
- CSV — flattened snapshot с 2 654 столбцами, в котором заполнено только 8,62%
  ячеек. Медиана — 174 заполненных поля на компанию, а 1 950 столбцов
  заполнены не более чем у 5% компаний.

В наборах нет пересечения по ИНН или ОГРН, поэтому это не две сериализации
одних и тех же строк. Однако после сворачивания индексов массивов в CSV и
распаковки Mongo Extended JSON-обёрток нормализованные схемы совпадают: 120 из
120 scalar-path templates. Следовательно, это две выборки одного контракта.

**Основным demo-форматом выбираем JSON.** В нём сохранены вложенные объекты и
массивы, поэтому не возникает тысяч искусственных колонок и ограничений на
максимальную длину массива. CSV остаётся fallback-адаптером и материалом для
contract/parity tests.

JSON нельзя сразу отдавать в Pydantic без адаптации: даты представлены как
`{"$date": ...}`, а часть денежных значений — как `{"$numberLong": ...}`.
Source adapter должен преобразовать их в timezone-aware `datetime` и
`Decimal`, сохранив исходный путь и raw hash.

Дополнительные последствия:

- в каждом наборе смешаны юридические лица и ИП, которые нельзя сравнивать как одну
  однородную группу;
- даты снимков различаются, поэтому у каждого факта должна сохраняться дата
  актуальности;
- `riskLevel` и `zskRiskLevel` — разные готовые сигналы источника, а не
  подтверждённая методика нашего скоринга;
- отсутствие значения может означать неприменимость, неполноту или отсутствие
  покрытия, но не отсутствие риска;
- контракт и snapshots имеют schema drift (`cofounders[].isActive` / `active`,
  а также фактический `UNKNOWN` у `baseInfo.riskLevel`), поэтому адаптер должен
  поддерживать aliases и сохранять неизвестные raw-значения;
- в данных есть очень длинные коллекции, противоречивые агрегаты, опечатки в
  кодах и поля с PII, поэтому
  raw-строки нельзя отправлять модели или писать целиком в trace.

В JSON встречается карточка с 1 744 исполнительными производствами. Для таких
разделов source должен возвращать агрегат, количество записей без суммы и
пагинированный top-N, а не всю коллекцию в LLM-контекст.

Следовательно, JSON или CSV сначала преобразуется в единый канонический
`CounterpartySnapshot`, а LLM получает только компактные факты и
`evidence_id`.

## 4. Целевая архитектура

```text
Browser / product UI
        │ AG-UI + SSE
        ▼
FastAPI application
        │
        ▼
LangGraph StateGraph ───────────────► session checkpointer
        │                              AsyncSqliteSaver для демо
        ├── query/entity resolver
        ├── deterministic analytics
        ├── cohort + ranking
        ├── one bounded LLM composer
        └── evidence validator
        │
        ▼
CounterpartySource port
        ├── JSON snapshot adapter      основной demo-source
        ├── CSV snapshot adapter       fallback / parity tests
        ├── mock adapter               тесты
        └── MCP / HTTP adapter         позже
```

Главная граница системы:

```text
источник → нормализованные факты → детерминированные findings
         → LLM-объяснение → серверная проверка evidence → ответ
```

LLM не получает права вычислять суммы, выбирать похожую группу, назначать
итоговый балл или создавать факты, отсутствующие в evidence ledger.

## 5. Граф выполнения

```text
START
  ↓
restore_session
  ↓
parse_request                         # сначала шаблон, контрольная сумма и нормализация названия
  ↓
understand_ambiguous_request          # языковая модель — только если правила не справились
  ↓
resolve_entities
  ├── ambiguous → ask_clarification → END
  ├── not_found → safe_not_found     → END
  ↓
route_intent
  ├── lookup ──────────────────────────────┐
  ├── compare_explicit ────────────────────┤
  ├── find_similar → build_cohort ─────────┤
  ├── full_report ─────────────────────────┤
  └── follow_up → reuse_session_context ───┤
                                          ↓
                                  load_snapshots
                                          ↓
                         analyze_companies in parallel
                                          ↓
                           compare_and_rank if requested
                                          ↓
                                  compose_answer
                                          ↓
                                validate_grounding
                                  ├── valid → persist → END
                                  └── invalid → one repair
                                                   ├── valid → persist → END
                                                   └── safe template → END
```

Для анализа нескольких компаний LangGraph выполняет одинаковый
детерминированный анализ через fan-out/map и затем reduce. Отдельный LLM-агент
на каждую компанию в MVP не нужен.

## 6. Поиск, похожие компании и сортировка

### Разрешение компании

1. ИНН и ОГРН/ОГРНИП очищаются, проверяются по длине и контрольной сумме, затем
   ищутся только по exact match.
2. Название нормализуется: регистр, кавычки, пробелы и ОПФ. Сначала выполняется
   exact match по нормализованному названию.
3. Если exact match не найден, используется `RapidFuzz` и пользователю
   показываются кандидаты. Агент не выбирает неоднозначную компанию молча.
4. Несколько ИНН или названий создают явный shortlist и ветку сравнения.
5. Фразы «его», «эту компанию», «сравни с предыдущей» разрешаются только через
   `SessionContext` текущего диалога.

### Построение похожей группы

Сначала применяются правила сопоставимости, затем ranking:

1. раздельно ЮЛ и ИП;
2. действующий статус и сопоставимая дата отчёта;
3. основной ОКВЭД: точный код, затем класс/раздел при недостатке кандидатов;
4. размер компании или диапазон выручки;
5. возраст бизнеса;
6. регион, если он доступен и важен пользователю.

Если группа слишком мала, фильтры ослабляются ступенчато, а интерфейс явно
показывает, какие условия были ослаблены. Риск-сигналы не используются для
поиска «похожих», иначе cohort заранее смещается в сторону желаемого результата.

Ranking должен быть прозрачной версионированной функцией. Отдельно показываются:

- риск или набор существенных findings;
- полнота и качество данных;
- критерии сопоставимости;
- неизвестные значения.

LLM объясняет результат ranking, но не выполняет его.

## 7. Память одной сессии

В checkpoint хранится компактное прикладное состояние:

```text
SessionContext
├── messages
├── active_company_ids
├── resolved_entities
├── current_cohort + cohort_policy
├── active_filters + ranking_mode
├── deal_context
├── pending_disambiguation
├── snapshot_ids + report_dates
├── finding_ids + referenced_evidence_ids
└── last_report_id
```

Raw JSON/CSV и полные `CounterpartySnapshot` в checkpoint не кладутся: они
повторно загружаются по `snapshot_id`.

Для демо используем `AsyncSqliteSaver`, чтобы обновление страницы или
перезапуск процесса не разрушили диалог. Новая сессия получает новый
`thread_id`. На backend ключ состояния должен включать доверенный `user_id` и
`thread_id`; сам `thread_id` не является авторизацией. Если нужен строго
одноразовый стенд без перезапусков, `InMemorySaver` допустим как упрощение.
Checkpoints имеют TTL и не используются для персонализации новой сессии.

Переходный `/api/chat` до сборки LangGraph хранит не более восьми сообщений в
памяти одного процесса и очищает их по TTL. Это временная реализация для
проверки UI и DSLab; она не заменяет описанный SQLite checkpointer.

## 8. Канонические контракты

```text
CounterpartySnapshot
├── snapshot_id, report_at, source, raw_hash, schema_version
├── Party
│   ├── party_type, inn, ogrn_or_ogrnip, kpp?
│   ├── names, status, registration_date, address?
│   └── company_size?, contacts?, tax_regimes[]
├── BankRiskAssessment
│   ├── raw_color: GREEN | YELLOW | RED | null
│   ├── display_color: GREEN | YELLOW | RED | GREY
│   ├── assessed_at
│   ├── source: bank_scoring
│   └── methodology_disclosed: false
├── Activities: primary_okved + secondary_okved[]
├── OwnershipAndRelations: authorized_person?, founders[], related_parties[]
├── FinancialStatement[]
├── ArbitrationAggregate[] + ArbitrationCase[]
├── EnforcementProceeding[]
├── Inspection[]
├── License[]
├── ProcurementAggregate[]
├── ProviderSignal[]
└── DataQualityReport
```

`BankRiskAssessment` — внешний результат закрытого банковского скоринга. Агент
не рассчитывает, не изменяет и не объясняет его скрытые факторы. Значения:
`GREEN` — надёжный контрагент, `YELLOW` — требует внимания, `RED` — в зоне
риска, `GREY` — нет данных для оценки. Банковский цвет, `baseInfo.riskLevel` и
прозрачные `Finding` агента выводятся раздельно. Если поле отсутствует, исходное
значение остаётся `null`, а `GREY` используется только как представление
состояния «нет данных».

```text
Finding
├── code, company_id, category, severity
├── statement
├── evidence_ids[]
└── data_status: confirmed | partial | conflicting | insufficient | inapplicable
```

```text
Evidence
├── evidence_id, company_id, snapshot_id
├── evidence_kind: observed | provider_assertion | derived | data_gap
├── field_paths[], typed_value, unit/currency, period
├── report_at, source, raw_hash
├── quality_status + coverage_status
└── pii_class
```

```text
QueryPlan
├── intent: lookup | compare_explicit | find_similar | full_report | follow_up
├── identifiers: inn | ogrn | company_name
├── filters: region | okved | size | revenue_band | active_only
├── ranking_mode
└── deal_context
```

Источник должен возвращать структурированный outcome:

```text
success | empty | partial | unavailable | denied | invalid
```

## 9. Ingestion snapshot

1. Определить формат, сохранить hash исходного файла и schema fingerprint.
2. Для JSON распаковать только разрешённые Extended JSON-типы: `$date`,
   `$numberLong` и при появлении в контракте `$numberDecimal`/`$oid`.
3. Для CSV разобрать flattened paths и восстановить коллекции по индексам.
4. Оба пути передать в один общий mapper; пустые значения не превращать в нули.
5. Определить тип субъекта и валидировать ИНН/ОГРН.
6. Преобразовать деньги в `Decimal`, даты в timezone-aware `datetime`, признаки
   в `bool`.
7. Нормализовать известные aliases и confusable-коды, сохранив `raw_code`.
8. Сверить агрегаты с деталями и сформировать data-quality findings.
9. Создать атомарный evidence ledger.
10. Построить индексы по ИНН, ОГРН, нормализованному названию и ОКВЭД.

Размер обоих demo-snapshots позволяет выполнить это один раз при старте или
заранее командой подготовки demo-data. `Polars`, DuckDB и vector DB для этого
объёма не обязательны; их стоит добавлять только при измеренной потребности.

## 10. Стек

### Runtime

| Слой | Выбор | Назначение |
|---|---|---|
| Python | **3.12** | Совпадает с референсом и поддерживается выбранными пакетами |
| Project manager/build | **`uv` + `uv_build`** | `.venv`, зависимости, scripts, build и воспроизводимый `uv.lock` |
| Workflow/state | **`langgraph`** | Явный граф, streaming, fan-out и session checkpoint |
| Provider client | **`openai` SDK** | DSLab Chat Completions: `qwen3.7-plus`, reasoning выключен по умолчанию |
| LLM orchestration | **`langchain-core`, `langchain-openai`** | Messages/tools внутри будущих LangGraph-узлов |
| Contracts/config | **`pydantic` v2, `pydantic-settings`** | Domain schemas, structured output и env settings |
| API | **`fastapi`, `uvicorn`** | HTTP, health, lifespan и static demo UI |
| Agent transport | **`ag-ui-langgraph` + SSE** | Переиспользуем интеграцию SuperVisor, если frontend поддерживает AG-UI |
| HTTP | **`httpx`** | Общий async client для будущих источников и integration tests |
| Name search | **`rapidfuzz`** | Только поиск кандидатов по названию, не принятие решения |
| Session persistence | **`langgraph-checkpoint-sqlite`** | Устойчивая память локальной demo-сессии |
| Eval fixtures | **`PyYAML`** | Версионируемые сценарии и ожидаемые маркеры |

### Dev

- `pytest`, `pytest-asyncio`, `pytest-cov`;
- `ruff` для lint и format;
- `mypy` или `pyright` — выбрать один, не оба;
- `hypothesis` опционально для ИНН/ОГРН, unflatten и risk rules.

### Опциональные extras, не MVP

- `mcp` / FastMCP — read-only интерфейс к тем же use cases;
- `langchain-ollama` — если модель запускается через Ollama, а не через
  OpenAI-compatible gateway;
- `polars` — только если ingestion станет заметным bottleneck;
- Postgres checkpointer — для production/multi-worker.

Сейчас не нужны: `deepagents`, `pydantic-ai`, vector DB, embeddings, RAG,
отдельный LLM для каждого тематического блока, Redis и брокер задач.

Версии задаются совместимыми диапазонами в `pyproject.toml`, а точные версии
фиксируются созданным `uv.lock`. Lock не редактируется вручную и коммитится в
Git. В CI используется `uv sync --locked`.

## 11. Компактная карта репозитория MVP

```text
.
├── CONTEXT_PACK.md
├── README.md
├── AGENTS.md
├── pyproject.toml
├── .python-version
├── .env.example
├── .gitignore
├── docs/
│   └── architecture.md
├── data/
│   └── README.md
├── src/
│   ├── main.py
│   └── counterparty_agent/
│       ├── __init__.py
│       ├── config.py
│       ├── models.py
│       ├── sources.py
│       ├── analysis.py
│       ├── graph.py
│       ├── llm.py
│       ├── app.py
│       └── ui/
│           └── index.html
└── tests/
    ├── README.md
    ├── test_scaffold.py
    ├── test_app.py
    └── test_llm.py
```

`uv.lock` появится после первого `uv sync` и должен быть закоммичен. Пакет пока
намеренно плоский: новые подпакеты создаются только когда в модуле появятся две
независимые ответственности или нескольким участникам станет трудно работать
без конфликтов. Предметная логика при этом остаётся в `analysis.py`, доступ к
данным — в `sources.py`, оркестрация — в `graph.py`, транспорт — в `app.py`.
Один автономный `ui/index.html` служит кликабельным UX-контрактом до выбора
полноценного frontend-стека.

## 12. Что именно взять из SuperVisor

Переиспользовать как паттерн:

- `pyproject.toml`, `uv` workflow и `src`-layout;
- `config.py` с typed settings;
- одну model factory с настраиваемым `base_url` в `llm.py`;
- composition root в `app.py` и возможность подменять model/source/checkpointer;
- shared `httpx.AsyncClient` на lifespan;
- FastAPI + AG-UI endpoint над тем же graph;
- outcome taxonomy, mock contour, trace collector;
- unit, contract, integration, route и benchmark/eval tests.

Заменить:

- `create_deep_agent`, `task`, subagents и todo planning — на собственный
  `StateGraph`;
- prompt-based routing — на typed `QueryPlan` и условные edges;
- source-specific business logic в tools — на `domain` и use cases;
- raw source responses — на канонические models + evidence ledger;
- `InMemorySaver` — на SQLite для устойчивого demo;
- process-per-company — на entity resolution внутри каждого запроса;
- полные tool payloads в trace — на метаданные и редактированные summary.

Не переносить filesystem/shell tools, `verify=False`, упаковку секретов или
контурные deployment-workarounds без отдельной необходимости.

## 13. Composition root

На этапе компактного MVP `app.py` — единственное место сборки приложения:

```text
Settings
→ shared HTTP client
→ JsonCounterpartySource | CsvCounterpartySource | MockSource | future McpSource
→ DSLab adapter (`qwen3.7-plus` через OpenAI Chat Completions)
→ domain services
→ checkpointer
→ build_graph(dependencies)
→ FastAPI / AG-UI
```

`models.py` и `analysis.py` не знают о FastAPI, LangGraph, JSON/CSV, MCP или
конкретной LLM. `graph.py` только оркестрирует, а `sources.py` переводит внешние
форматы в канонические контракты. При росте `app.py` первым выносится отдельный
`bootstrap.py`.

## 14. Минимальный набор evals до демонстрации

1. JSON и CSV одного schema contract преобразуются в одинаковые канонические
   модели на специально подготовленной parity-fixture.
2. Extended JSON-типы преобразуются без потери даты, точности и provenance.
3. Exact lookup по ИНН/ОГРН и валидация контрольной суммы.
4. Exact/fuzzy lookup по названию и обязательное уточнение при неоднозначности.
5. Сравнение явно выбранных компаний.
6. Построение сопоставимой группы с показанными критериями и ослаблениями.
7. Follow-up: «сравни его с предыдущей» в одной сессии.
8. Изоляция двух `thread_id` и двух пользователей.
9. Отсутствующие данные не превращаются в положительный вывод.
10. Каждый factual claim содержит существующий `evidence_id` нужной компании и
   версии snapshot.
11. Денежные суммы, периоды и статусы совпадают с evidence.
12. Ошибка, empty и partial source дают разные безопасные ответы.
13. PII и raw snapshot не появляются в trace.
14. Один и тот же snapshot + версии правил дают воспроизводимые findings.

Главные метрики агента:

- factual claims with valid evidence: **100%**;
- unsupported factual claims: **0**;
- entity-resolution accuracy;
- покрытие набора вопросов;
- latency и число LLM-вызовов;
- доля корректных отказов `insufficient_data`;
- сохранение и изоляция session context.

## 15. Когда вернуться к Deep Agents

Пересматривать решение стоит только если одновременно появляются несколько
условий:

- много длинных неструктурированных документов;
- маршрут исследования заранее неизвестен;
- контекст промежуточных tool calls системно переполняет окно;
- специалистам нужны разные инструменты, модели и изолированные контексты;
- запросы становятся длительными и возобновляемыми;
- A/B-eval показывает прирост полноты без роста неподтверждённых утверждений и
  неприемлемой задержки.

До этого явный LangGraph проще тестировать, объяснять кейсодателю и защищать на
демонстрации.

## Источники решения

- [Карта продуктового процесса](../CONTEXT_PACK.md).
- [Индекс артефактов кейса](../artifacts/INDEX.md): постановка,
  экспорт Q&A и PDF-презентация.
- Технический референс: путеводитель по SuperVisor из материалов команды.
- Локальные данные: `contractors_audit.snapshot.json` и
  `contractors_audit.snapshot_C12613591.csv` (не коммитятся из-за реквизитов и
  потенциальных PII).
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents)
- [uv: locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)
