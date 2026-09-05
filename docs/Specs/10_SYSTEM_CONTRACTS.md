# 10. Общие контракты всех частей системы

Версия 1.1 · 05.09.2026. [Индекс](00_OVERVIEW_AND_INDEX.md) · [Физические сущности и mapping](02_DATA_AND_STORAGE.md).

Это единый реестр прикладных DTO и операций. Имена полей ниже — целевой контракт нашего MVP. Они не объявляются встроенными API LangGraph или assistant-stream. Данные контрагентов опираются на фактическую выгрузку; project/run/document — новые сущности приложения. RPC wire envelope адаптируется к закреплённой версии assistant-stream, а смысл и типы полей сохраняются.

## 1. Общие правила сериализации

- Идентификаторы ресурсов — UUID-строки; ИНН/ОГРН/КПП/номера дел и лицензий — строки.
- Decimal передаётся строкой без разделителей тысяч: `"1920000.00"`; float для денежных вычислений запрещён.
- Деньги: `{amount: DecimalString, currency: "RUB"}`. Валюта RUB для чисел отчёта — документированная интерпретация fixture, не выдуманное поле источника; для предложения задаётся пользователем/документом.
- Timestamp — ISO 8601 UTC; календарная дата — YYYY-MM-DD; финансовый год — integer. Не заменять year на report_date.
- `null` не равен 0, пустой массив не всегда доказывает отсутствие события. Для полноты используется availability.
- Каждая схема имеет schema_version. Response metadata: request_id, generated_at; version/checksum там, где нужно кеширование.
- Вход: Pydantic validation, лимиты размера, whitelist полей; серверные идентификаторы владельца не подменяются body.
- REST errors — HTTP status + Error DTO. После начала stream ошибка идёт в поддерживаемое библиотекой состояние/ошибку потока; HTTP 200 начала стрима не означает успешного завершения run.

## 2. Базовые DTO

### EvidenceRef

| Поле | Тип | Смысл |
|---|---|---|
| id | string | Стабильный серверный ID ссылки |
| kind | report_field / document_fragment / user_message / artifact_section / derived | Вид источника |
| report_id, company_id | UUID/null | Снимок и компания |
| source_path | string/null | JSON Pointer относительно исходного объекта report |
| document_id, fragment_id | UUID/null | Документ и извлечённый фрагмент |
| page | integer/null | Страница только если известна |
| locator | object/null | pdf_page / spreadsheet_range / word_block / text_lines; точные поля ниже |
| artifact_id, artifact_version | UUID/integer/null | Версия прикреплённого анализа; не первичный report fact |
| message_id | string/null | Реплика пользователя как источник |
| period | integer/string/null | Год или период факта |
| input_refs | EvidenceRef ID[] | Основания вычисленного значения |
| rule_version | string/null | Версия вычисления |

Для report_field нужны report_id/source_path; для document_fragment — document_id/fragment_id; для user_message — message_id; для derived — input_refs/rule_version. Ссылка проверяется сервером, модель не получает право создавать произвольный URL. Если нет внешней первичной ссылки, UI пишет «Предоставленный отчёт».

### FactValue

`{key, label, value, value_type, unit?, currency?, period?, availability, evidence_refs[], warnings[]}`.

value_type: decimal / integer / boolean / string / date / enum. Непустое значение строго соответствует типу. Для decimal — строка. availability: available / missing / present_empty / invalid / restricted. Если нет достоверного числа, value=null. Это API-представление; не путать restricted с состоянием исходного файла section_availability.

### Error

`{code, message, retryable, request_id, details?}`. Details — безопасная структурированная информация (например, invalid_fields), не stacktrace. Базовые code: validation_error, unauthorized, forbidden, not_found, conflict, limit_exceeded, source_missing, parse_failed, dependency_unavailable, timeout, cancelled, internal_error. Для чужого ресурса допустимо not_found, чтобы не раскрывать существование.

## 3. DTO отчёта и детерминированного слоя

### CompanyOverview

`{schema_version, company:{id,inn,ogrn?,short_name,full_name?}, report:{id,source_report_at,ingested_at,source_kind:"provided_snapshot"}, status, bank_risk, zsk, facts:FactValue[], available_sections[], warnings[], rule_version}`.

bank_risk: `{raw_value, label, display_level, evidence_refs}` — исходная оценка без нового скоринга. zsk: `{raw_value, display_level, display_note, policy_version, evidence_refs}` — отдельная политика. До подтверждения mapping YELLOW/RED — neutral/«Отображение требует уточнения». GREEN не подменяет оценку финансовой устойчивости. Unknown сырой enum сохраняется, отображение neutral.

### ReportSection

`{report_id, section, availability, records[], facts[], page:{limit,next_cursor,has_more}, total_records?, warnings[], rule_version}`.

records — discriminated union: FinancialPeriod / Proceeding / ArbitrationAggregate / ProcurementAggregate / License / Inspection / RelatedEntity / Activity / ProfileRecord / RiskSignal. Pydantic валидирует раздел и соответствующий тип записи, не произвольный Any JSON.

| Тип | Основные поля | Реальный источник |
|---|---|---|
| FinancialPeriod | year, proceeds, profit, total_assets, equity, cash, receivables, accounts_payable; каждое nullable и с refs | finReports[].common/assets/liabilities |
| Proceeding | id, active, number, date, amount, evidence_refs | executionProceedings[] |
| ArbitrationAggregate | aggregation: year/status, role, year?, status?, count?, amount?, evidence_refs | arbitrationCases[] или arbitrationByStatus; это не отдельное дело |
| ProcurementAggregate | year, law_code, winners_count, contracts_count, contracts_amount, evidence_refs | procurements[] |
| License | number, name, authority, issue_date, status_raw, evidence_refs | licenses[] |
| Inspection | external_id, form, authority, start_date, end_date, status_raw, evidence_refs | inspections[] |
| RelatedEntity | inn?, ogrn?, name, available_company_id?, evidence_refs | relatedCompanies[]; доступность полного report проверяется отдельно |
| Activity | code, description, is_primary, evidence_refs | kindsOfActivityInfo |
| RiskSignal | code, source_name, polarity, chapter?, interpretation_note?, evidence_refs | reputationalRisks; source_name не считается проверенным выводом |

Полный mapping физической схемы — 02. Отсутствующие исходные поля остаются nullable, а не заполняются «типичным» значением.

### Comparison

`{id?,report_ids[],criteria[],year_policy,rows:[{company,report,cells:FactValue[],status,warnings[]}],warnings[],rule_version}`.

year_policy: common_latest / latest_available / explicit; при explicit обязателен year. Default latest_available с видимыми периодами. В UI REST-сравнение может дополнять строки proposal facts из workspace с отдельными refs. MCP-сравнение возвращает только отчётные факты; это один базовый DTO с явно отдельным полем proposal_facts в расширении ProjectComparison. Нет winner_id или общего score от детерминированного слоя.

## 4. DTO проекта и документов

### Project

`{id,title,default_thread_id,threads_count,context_version,workflow_status,companies[],last_open_question?,latest_artifact?,latest_decision?,created_at,updated_at}`.

workflow_status: in_progress / needs_information / decision_recorded. Это не run status и не оценка риска. В проекте несколько threads; история каждого изолирована. При outcome need_more_info статус needs_information; новый документ после решения даёт freshness marker, не удаляет историю решения.

### ProjectFact

`{id,key,value,value_type,unit?,currency?,company_id?,provenance_ref,confirmation_status,version}`.

key whitelist: counterparty_role, subject, amount, payment_type, advance_percent, delivery_deadline, delivery_terms, user_priority; расширения через схему. role: supplier / buyer / contractor / other / unknown. confirmation_status: user_confirmed / extracted_unconfirmed / inferred. Изменение company-specific условия требует company_id.

### Document

`{id,filename,mime,size,company_id?,parsing_status,error?,created_at,fragments_available}`.

parsing_status: uploaded / processing / ready / failed / deleted. Максимум 10 МБ, 10 активных файлов. Storage key и внутренний путь в UI не возвращаются. Fragment: `{id,document_id,locator,page?,text?,bbox?,extraction_method,extraction_status}`. Для vision без точных координат bbox=null; цитаты проверяются по доступному представлению. OCR не делает инструкцию внутри файла доверенной командой.

### AnalysisArtifact и UserDecision

AnalysisArtifact: `{id,version,project_id,based_on_context_version,report_ids[],question,summary,grounds[],unknowns[],next_actions[],evidence_refs[],freshness,created_by_run_id,source_thread_id,created_at}`. grounds содержит текст и refs; unknowns — конкретное недостающее сведение, не общий disclaimer. freshness: current / outdated / source_removed.

UserDecision: `{id,outcome,company_ids[],rationale,conditions[],based_on_artifact_id?,based_on_artifact_version?,context_version,evidence_refs[],author_user_id,created_at,supersedes_id?}`. outcome: ready / ready_with_conditions / not_ready / need_more_info. author_user_id только из авторизации. Для ready_with_conditions и need_more_info — минимум одно конкретное условие/неизвестное. Отсутствие AI-артефакта не запрещает записать собственное решение; основания пользователя фиксируются.

## 5. REST: UI ↔ UI Backend

Префикс `/api/v1`. Все проектные операции проверяют tenant scope. GET без мутаций; списки — cursor pagination, default limit 20, max 100. Объём сравнения ограничен 20 компаниями независимо от пагинации списка проектов.

Повтор запроса с уже использованным `client_request_id` и тем же payload отвечает `200` с заголовком `idempotent-replay: true` и телом первого созданного ресурса, а не `201`: клиент должен различать «создано» и «это уже было». Запрос, пришедший, пока первый ещё исполняется, получает `409 conflict` с `details.reason=request_in_flight` и `retryable=true`; тот же id с другим payload — `409 conflict` с `details.reason=request_id_reused` (решение пользователя, волна F).

| Метод и путь | Вход | Ответ / эффект |
|---|---|---|
| POST /projects | title?, initial_question?, client_request_id | 201 Project (повтор — 200, см. выше); создаёт project+первый thread mapping, но не запускает LLM |
| GET /projects | cursor?, limit?, query? | Page<Project> |
| GET /projects/{p} | — | Project |
| PATCH /projects/{p} | title | Project; rename не меняет context_version |
| DELETE /projects/{p} | expected_version? | 202 deletion status; сначала закрыть доступ/отменить run, затем cleanup |
| GET /companies | inn? / query?, cursor?,limit? | Локальные результаты; no external search |
| POST /projects/{p}/companies | items:[{inn или company_id}], expected_context_version | Per-item added/already_present/not_found/invalid; новая context_version |
| DELETE /projects/{p}/companies/{c} | expected_context_version | Новый состав; старые ссылки сохранены |
| GET /projects/{p}/facts | — | ProjectFact[] |
| PATCH /projects/{p}/facts | changes[], expected_context_version | Новые версии фактов + context_version |
| GET /reports/{r}/overview | — | CompanyOverview, только доступный report |
| GET /reports/{r}/sections/{section} | Разрешённые фильтры, limit,cursor | ReportSection |
| POST /projects/{p}/comparisons | report_ids[],criteria[],year_policy,year? | ProjectComparison; сервер проверяет принадлежность reports проекту |
| POST /projects/{p}/documents | multipart file, company_id?, question_id? | 202 Document; фон обработки документа |
| GET /projects/{p}/documents | — | Document[] |
| GET /projects/{p}/documents/{d} | — | Document |
| GET /projects/{p}/documents/{d}/content | — | Авторизованный оригинал, корректный content type |
| GET /projects/{p}/documents/{d}/fragments | page?, cursor?, limit? | Page<Fragment> |
| DELETE /projects/{p}/documents/{d} | — | Удаление и пометка зависимых выводов |
| GET /projects/{p}/evidence/{ref} | — | Разрешённый факт/фрагмент, место возврата задаёт UI |
| GET /projects/{p}/artifacts | kind?, latest? | AnalysisArtifact[]/последние версии |
| GET /projects/{p}/decisions | — | UserDecision[] |
| POST /projects/{p}/decisions | outcome,rationale,conditions,company_ids,versions | 201 UserDecision |
| GET /projects/{p}/threads | cursor?,limit? | Page<ThreadSummary> |
| POST /projects/{p}/threads | title?,client_request_id | Новый ThreadSummary |
| PATCH /projects/{p}/threads/{t} | title?,archived? | ThreadSummary; проверка активного run при архивировании |
| GET /projects/{p}/threads/{t}/conversation | — | PublicAgentState + active_run_id, из проекции выбранного thread |

POST companies: сначала preview в UI, затем добавление валидных. Если валидные новые записи превышают оставшийся лимит 20, batch не применяет произвольные первые N, возвращает limit_exceeded. Невалидная строка не обязана блокировать другие записи, если лимит соблюдён. Optimistic conflict — 409 с актуальной context_version.

## 6. RPC: UI ↔ Agent Service

Префикс `/rpc/agent`, отдельный router и DTO. Это command API поверх HTTP с библиотечным стримингом, не JSON-RPC 2.0. RPC не дублирует CRUD.

| Операция | Семантический вход | Результат |
|---|---|---|
| POST /chat | project_id, thread_id, client_request_id, commands[], stream:true | assistant-stream поток PublicAgentState |
| POST /runs/{run_id}/subscribe | project_id, known_revision? | Новая подписка на актуальное состояние без повторного run |
| GET /runs/{run_id} | — | RunInfo + публичная последняя ревизия |
| POST /threads/{thread_id}/follow-ups | project_id, client_request_id, message, artifact_refs?, document_ids?, evidence_refs? | 202 PendingCommand: немедленный приём во время tools |
| POST /runs/{run_id}/cancel | client_request_id | Идемпотентная отмена; status cancelling/cancelled |
| POST /runs/{run_id}/continue | client_request_id, answer? | Новый run/resume с checkpoint для interrupted/awaiting_input |

`subscribe`/resume hooks сопоставляются с возможностями закреплённого assistant-ui runtime (resumeApi/resumeStateApi или небольшой transport adapter). Конкретная форма wrapper — V01/V02. Семантика выше обязательна; не создавать параллельный собственный формат streaming chunks.

Минимальная команда: `add-message` с message ID, текстом и ссылками `document_ids[]`, `artifact_refs[]`, `evidence_refs[]`, `company_ids[]`. Прикладная команда `reanalyze` несёт changed_context_version/причину; `continue` — ответ на pending question или возобновление прерванного run. Модельные/system/tools config из браузера не исполняются. Если assistant-ui присылает state, сервер не доверяет ему как памяти агента.

Пример семантического запроса (UUID для примера, не ID реальной базы):

```json
{
  "project_id": "00000000-0000-4000-8000-000000000001",
  "thread_id": "00000000-0000-4000-8000-000000000002",
  "client_request_id": "00000000-0000-4000-8000-000000000003",
  "stream": true,
  "commands": [{
    "type": "add-message",
    "message": {
      "id": "client-msg-1",
      "text": "Можно ли перечислять 80% аванса?",
      "document_ids": [],
      "evidence_refs": [],
      "company_ids": []
    }
  }]
}
```

Это доменная форма; adapter переводит message в `parts`/прочие поля runtime по закреплённой версии. Не переписывать приложение при изменении имени поля библиотеки.

RunInfo: `{id,thread_id,project_id,status,started_at,finished_at?,based_on_context_version,last_public_revision,error?}`.

Run status: accepted → running → completed / awaiting_input / failed / cancelled / interrupted; cancelling — промежуточный. completed означает завершение конкретного запроса, а не согласие пользователя сотрудничать. awaiting_input — сохранённый вопрос, фон не продолжает бессмысленные вызовы. Interrupted после restart не отображается как бесконечно running.

## 7. PublicAgentState: агент → UI

`{schema_version,project_id,thread_id,run:RunInfo?,revision,messages[],activities[],pending_commands[],pending_questions[],artifact_refs[],context_version,save_status}`.

Message: `{id,role,blocks[],status,created_at}`; role user/assistant/system_notice; status pending/streaming/complete/partial/error. Block union: text / evidence_reference / document_reference / analysis_reference / comparison_reference / question. Для custom renderers — whitelist типов, никакого исполняемого HTML или React-кода от модели.

Activity: `{id,kind,label,status,evidence_refs[],started_at?,finished_at?}`. kind reading_report / reading_document / comparing / calculating / updating_analysis / skill_invocation; status running/completed/failed. Это публичный слой, не зеркало всех low-level callbacks. Internal reasoning и prompts отсутствуют.

Поток обновляет публичную проекцию через штатные операции assistant-stream. Это не самостоятельно спроектированный второй event protocol. Сохранение результата подтверждается сервером до `save_status:"saved"`. При reconnect достаточно восстановить актуальную проекцию и новые изменения; воспроизведение каждого потерянного токена не является требованием MVP. Завершённые сообщения и артефакты должны сохраниться полностью.

## 8. MCP tool contracts

Общий envelope: `{schema_version,status,data,errors[],warnings[],source_report_ids[],rule_version}`. status ok / partial / not_found / unavailable. Protocol error и бизнес-неполнота различаются. Structured output и input schemas генерируются из Pydantic. max output records и лимиты размера контролируются сервером.

| Tool | Input | Output data |
|---|---|---|
| get_company_overview | XOR inn:string / report_id:UUID | CompanyOverview |
| get_report_section | report_id,section enum,filters?:{years?,active?,role?,status?},cursor?,limit=20≤100 | ReportSection |
| compare_companies | report_ids:2..20 unique,criteria[],year_policy,year? | Comparison без workspace proposal_facts |

Filters валидируются в зависимости от section; unknown filter — validation_error. Criteria whitelist соответствует данным: bank_risk, status, financials, proceedings, arbitration, activities, licenses, procurement, completeness. Сравнение не принимает произвольный expression/SQL и не вычисляет новый риск-балл.

## 9. Внутренние contracts: документы, расчёты и persistence

- DocumentReader.read(project_scope, document_id, fragment_selector) → Fragment[]; права и размер проверяются до чтения.
- ProjectContextReader.get(project_scope) → ContextSnapshot с context_version, подтверждёнными facts, индексом документов, questions и refs текущих reports.
- AnalysisWriter.save(project_scope, run_id, artifact, expected_context_version) → Artifact/version + freshness. Расхождение версии не теряет результат, но делает его outdated.
- TransactionCalculator.calculate(typed inputs) → FactValue[] с derived refs; Decimal, валидация валюты и диапазона аванса 0..100.
- Checkpointer — штатный интерфейс LangGraph; thread_id берётся из Project mapping. Модель не выбирает произвольный checkpoint namespace.
- ConversationProjector.save(thread_id, public_state, revision) → сохранённая ревизия; поздний stale update не перезаписывает более новую.

Эти interfaces — границы shared-пакетов, не новые сетевые сервисы. У RunManager task ownership отдельно от подписчиков; допускается in-process реализация в MVP при одном экземпляре сервиса.

## 10. Числовой fixture и доказательства

Для исходного отчёта INN `7449088645` последнее финансовое значение `finReports[0].common.year` = 2025. `common.proceeds` = 74586000; `liabilities.capitals` = -300000; `assets.currentAssets.bankroll` = 355000. Для этих значений source_path соответственно `/finReports/0/common/proceeds`, `/finReports/0/liabilities/capitals`, `/finReports/0/assets/currentAssets/bankroll`, относительно report. Импортёр должен проверить год, а не считать индекс 0 всегда последним периодом.

Аванс `1920000.00` не находится в snapshot: это derived от синтетических условий цены `2400000.00` и 80%. Аванс Б `520000.00` — от `2600000.00` и 20%. Ссылка на аванс обязана вести к условиям и формуле, а не к финансовому JSON компании. Все учебные условия отмечены synthetic/demo.

## 11. Границы доверия и совместимости

Контракт не разрешает автоматически передавать весь graph state наружу. Внешний MCP получает отдельную whitelist-проекцию; внутренний PublicAgentState для собственного UI не используется как внешний экспорт. Даты, источники, суммы, статусы и ownership валидируются кодом. Текст документа — данные для анализа, не system instruction.

Не гарантируется, что все перечисленные имена endpoints уже существуют в библиотеках. Это наше ТЗ. V01 проверяет wiring assistant-stream; V02 — disconnect; V05 — FastMCP. Совместимость фиксируется в lockfiles и коротких контрактных тестах. Автоматическая отмена callback библиотеки не должна нарушать согласованное продолжение run после закрытия страницы.

## 12. Дополнение 1.1: сессии, артефакты, skills и follow-up

ThreadSummary: `{id,project_id,title,status,last_activity_at,active_run_id?,last_open_question?,archived_at?}`. id — canonical thread_id, в тексте сессия=чат. Авторизационная session cookie никак не заменяет thread_id. Project.default_thread_id определяет первоначально открываемый чат; явный URL thread имеет приоритет.

ArtifactAttachment: `{artifact_id,version,section_id?}`. Сервер проверяет проект и существование immutable версии. Отправка в соседний чат проекта разрешена, межпроектный доступ по умолчанию запрещён. Preview: `{title,version,source_thread_id,created_at,freshness,available}`. Более новая версия не меняет отправленную ссылку. Прикреплённый AI-вывод не становится исходным фактом без его evidence refs.

Locator union:
- `{kind:"spreadsheet_range",sheet:string,range:string}`; для ячейки range=`B12`; sheet обязательна.
- `{kind:"word_block",paragraph_id?:string,table_id?:string,row?:integer,column?:integer}`; минимум один block ID, не выдуманный номер страницы.
- `{kind:"pdf_page",page:integer,bbox?:number[]}`.
- `{kind:"text_lines",start_line:integer,end_line:integer}`.

TabularCell: `{sheet,address,value,type,formula?,cached_value?,cache_status,hidden?,evidence_refs[]}`. cache_status: present / absent / unknown_freshness; ни cached value, ни conversion не гарантируют актуальный recalculation. Не выполнять внешние формулы/макросы. Конвертация Markdown не заменяет координатный reader.

SkillInvocation: `{id,thread_id,run_id,skill_id,skill_version,source_commit,display_name,status,input_refs[],output_refs[],started_at?,finished_at?,error?}`. status loading / running / completed / failed / cancelled / cached. Public activity ссылается на skill_invocation_id и выводит «Использую навык …». Событие публикует executor/middleware, не произвольная реплика модели. allowed_tools manifest не является enforcement: инструменты разрешаются сервером.

PendingCommand: `{id,thread_id,run_id?,sequence,message_id,client_request_id,status,received_at,applied_at?,error?}`. Принимается HTTP 202 сразу независимо от активной подписки. status accepted / queued / applying / applied / cancelled / failed. Applied означает, что сообщение добавлено в контекст на безопасной границе и сохранено; не означает завершение ответа. GET `/rpc/agent/threads/{t}/pending-commands` возвращает состояния для восстановления UI; отмена queued command — DELETE `/rpc/agent/threads/{t}/pending-commands/{id}` до applying.

Политика доставки: при работающем инструменте очередь принимается сразу и обрабатывается перед следующим model call. Во время model streaming — следующий turn, без обещания hard interrupt. На границе завершения run атомарно решить, продолжать текущий или создавать следующий run того же thread; не потерять команду и не запустить два writer. Одинаковый client_request_id возвращает ту же command. Explicit cancel не запускает queued сообщения автоматически.

Internal SkillExecutor: `execute(skill_id,project_scope,thread_id,run_id,input_refs,operation) -> SkillResult{output_refs,extraction_metadata,warnings}`. Каталог versioned; чтение файлов только scoped. DocumentReader внутри skill возвращает Fragment/TabularCell и не обходится ad-hoc tool для тех же операций. Upload validation/хэширование — технический шаг до skill, не AI-задача.
