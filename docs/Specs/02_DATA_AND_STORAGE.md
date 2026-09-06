# 02. PostgreSQL, сущности и импорт исходных данных

Версия 1.1 · 05.09.2026. [Индекс](00_OVERVIEW_AND_INDEX.md) · [Общие контракты](10_SYSTEM_CONTRACTS.md).

## 1. Источник и фактическая полнота

Основной источник — приложенный `contractors_audit.snapshot(2).json`: массив из 100 объектов `{_id, report}`. CSV — дополнительная выгрузка; не объединять строки с JSON как новые компании без сверки происхождения. Источником канонического импорта MVP принять JSON. Первичный PDF описывает продукт; это не сто отдельных PDF-отчётов.

Профиль ниже проверен по файлу 05.09.2026. «Поле есть» отличается от «раздел содержит записи».

| Поле report | Поле присутствует | Есть непустые сведения | Как использовать |
|---|---:|---:|---|
| baseInfo, status, kindsOfActivityInfo, reportDate | 100 | 100 | Идентичность, статус, деятельность, дата снимка |
| reputationalRisks, arbitrationByStatus, zskRiskLevel | 100 | 100 объектов/значений | Вложенные разделы могут быть пусты; наличие объекта не доказывает наличие события |
| finReports | 75 | 67 | Финансовые периоды; 8 пустых массивов, 25 отсутствующих полей |
| foundersInfo | 75 | 75 | Капитал, учредители, уполномоченное лицо |
| taxSystem | 75 | 75 | Указанные системы налогообложения |
| phones | 100 | 29 | Контакты из предоставленного отчёта |
| executionProceedings | 100 | 53 | Производства, среди них действующие и завершённые |
| arbitrationCases | 44 | 44 | Годовые агрегаты, несмотря на название поля |
| coefficient | 19 | 19 | Значения коэффициентов без подтверждённых формул |
| procurements | 100 | 8 | Агрегаты участия/подписания контрактов по году и закону |
| licenses | 9 | 9 | Записи лицензий, не полный текст разрешений |
| inspections | 30 | 30 | Записи ведомственных проверок/предостережений |
| relatedCompanies | 61 | 61 | Краткие связанные записи; полный отчёт не гарантирован |
| branchesInfo | 2 | 2 | Дополнительные сведения о филиалах |

Данные имеют неодинаковые периоды; отсутствие нового года не заполнять данными прошлого. Суды в основном агрегированы: номера, фабулы и тексты решений не извлекаются из суммы/количества. Закупочные агрегаты не доказывают успешное исполнение. Краткая связанная запись не доказывает характер отношений. Нет исходных данных о счетах, платежах и клиентском профиле предпринимателя.

## 2. Две схемы

`reports`: immutable source + типизированные сущности + происхождение.

`workspace`: пользовательская работа + AI-предложения + служебное состояние фреймворка. Служебные таблицы LangGraph размещать в этой схеме через поддерживаемую конфигурацию подключения. Если выбранная версия требует отдельного namespace — оформить техническую корректировку, не переписывать checkpoint backend ради физического ограничения «ровно две схемы».

## 3. Сущности reports и точное соответствие JSON

Обозначение `report.*` относится к объекту report одной исходной записи. Все дочерние записи содержат `report_id`, локальный ID/ordinal и `source_path`; источник каждого периода сохраняется.

Датовые поля источника (`registration_date`, `status_date` и прочие `$date`) хранятся как точный момент времени, а не как календарная дата. Источник кодирует локальную полночь при разных смещениях UTC, поэтому перевод в дату требует угадывания часового пояса и смещает часть значений на сутки. Календарная дата вычисляется на слое отображения, где известен применяемый пояс; в хранилище сырое значение остаётся без потерь.

| Таблица | Ключевые поля | Источник |
|---|---|---|
| import_batches | id, file_name, sha256, imported_at, parser_version, counts | Метаданные импорта |
| companies | id, inn UNIQUE, ogrn, entity_type | report.baseInfo.inn, ogrn; тип не угадывать, если не подтверждён |
| report_snapshots | id, company_id, source_record_id, source_report_at, ingested_at, hash, raw_jsonb, batch_id, ingestion_status | _id; весь report; report.reportDate |
| company_profiles | report_id PK, short_name, full_name, kpp, okpo, address, registration_date, years_from_registration, email, website, company_size, bank_risk_raw, extra_jsonb | report.baseInfo.*; address — строка, registrationInfo.registrationDate/yearsFromRegistration — дата и возраст; исторические реквизиты привязаны к снимку |
| company_statuses | report_id PK, status_raw, status_date, reason_raw, extra_jsonb | report.status.status/date/reasonName; reason_raw соответствует reasonName, неизвестные вложенные поля сохранять |
| activity_codes | id, report_id, ordinal, code, description, is_primary | report.kindsOfActivityInfo.mainKindOfActivity, otherKindsOfActivity[] |
| financial_statements | id, report_id, ordinal, year, proceeds, profit, total_assets, current_assets, stocks, receivables, cash, noncurrent_assets, fixed_assets, balance_total_liabilities_side, equity, long_term_total, long_term_other, short_term_total, short_term_borrowed, accounts_payable, extra_jsonb | report.finReports[]; подробные пути ниже |
| reported_coefficients | id, report_id, year, sustainability, solvency, profitability, raw_jsonb | report.coefficient.year/sustainability/solvency/profitability; в проверенном файле объект |
| founders | id, report_id, name, inn, amount, share, date_from, active, extra_jsonb | report.foundersInfo.cofounders[] |
| authorized_persons | id, report_id, name, inn, position_name, position_date, extra_jsonb | report.foundersInfo.authPerson |
| capital_information | report_id PK, share_capital | report.foundersInfo.shareCapital; не смешивать с equity |
| contacts | id, report_id, type, value, extra_jsonb | report.phones[]; email из baseInfo может быть проекцией, без дублирования источника |
| tax_systems | id, report_id, full_name, short_name | report.taxSystem[] |
| risk_signals | id, report_id, polarity, code, name, chapter, extra_jsonb | report.reputationalRisks.negative[] / positive[] |
| zsk_assessments | report_id PK, raw_value, display_policy_version | report.zskRiskLevel |
| arbitration_totals | report_id PK, count, amount | report.arbitrationByStatus.commonCount/commonAmount; отдельно от детализаций |
| arbitration_status_aggregates | id, report_id, party_role, case_status, count, amount, raw_jsonb | report.arbitrationByStatus.plaintiffArbitration / defandantArbitration и вложенные Finished/Appealed/Pending |
| arbitration_year_aggregates | id, report_id, year, party_role, count, amount | report.arbitrationCases[].year, plaintiffCount/Amount, defendantCount/Amount; две строки на год при наличии |
| execution_proceedings | id, report_id, number, started_at, active, amount | report.executionProceedings[].number, date, active, amount |
| procurement_aggregates | id, report_id, year, law_code, winners_count, contracts_count, contracts_amount | report.procurements[].procurementsYear, federalLawCode, tenderWinnerCnt, contractSignedCnt, contractSignedAmt |
| licenses | id, report_id, number, name, authority, issue_date, status_raw | report.licenses[].number, name, issuingAuthority, issueDate, status |
| inspections | id, report_id, external_id, form, authority, start_date, end_date, status_raw | report.inspections[].erpId, form, authorityName, startDate, endDate, inspectionStatus |
| related_entities | id, report_id, inn, ogrn, name, related_company_id NULL | report.relatedCompanies[]; FK только если в выборке действительно есть совпадающая компания |
| branch_summaries | report_id PK, reported_count | report.branchesInfo.branchesCount |
| branches | id, report_id, name, address, extra_jsonb | report.branchesInfo.branches[].name/address |
| section_availability | report_id, section, source_state, record_count, warnings_jsonb | Результат парсинга; missing / present_empty / present / invalid |
| import_warnings | id, batch_id, report_id NULL, source_record_id NULL, severity, code, source_path, message | Результат парсинга; неизвестное поле, неизвестное значение enum или неразобранное число записывается сюда, а не приводится к значению по умолчанию |

`extra_jsonb` сохраняет остаток блока, но не заменяет нужные для фильтров и расчётов колонки. Нельзя терять неизвестные значения enum или неподдержанные поля без записи import warning: адресатом такой записи является `import_warnings`. `ordinal` хранит позицию элемента в исходном массиве, потому что JSON-массив упорядочен, а выборка из таблицы — нет; без него исходный `source_path` элемента невосстановим и evidence не разрешается обратно в источник. Raw JSONB сохраняет структуру; хэш исходного файла обеспечивает привязку к исходным байтам. JSONB не гарантирует сохранение порядка ключей исходного текста.

### Финансовые пути

| Колонка | Путь внутри finReports[i] |
|---|---|
| year, proceeds, profit | common.year, common.proceeds, common.profit |
| total_assets | assets.totalAssets |
| current_assets, stocks, receivables, cash | assets.currentAssets.total / stocks / receivables / bankroll |
| noncurrent_assets, fixed_assets | assets.uncurrentAssets.total / fixedAssets |
| balance_total_liabilities_side | liabilities.totalLiabilities |
| equity | liabilities.capitals |
| long_term_total | liabilities.longTermDuties.total; long_term_other — liabilities.longTermDuties.others |
| short_term_total, short_term_borrowed, accounts_payable | liabilities.shortTermLiabilities.total / borrowedFunds / accountsPayable |

**liabilities.totalLiabilities — итог пассива баланса, не сумма долга.** `capitals` — капитал по отчётности, `shareCapital` — уставный капитал. Дата снимка отчёта отличается от года финансовой отчётности. Отрицательный капитал не маркировать автоматически как доказанное банкротство. Поля/пути, не встретившиеся в импорте, нельзя считать присутствующими по этой таблице; schema report перечисляет реально обнаруженные варианты.

## 4. Сущности workspace

| Таблица | Назначение / основные поля |
|---|---|
| tenants, users, memberships | Владение и доступ; для MVP допускается ограниченный demo fixture |
| projects | id, tenant_id, owner_id, title, default_thread_id NULL, context_version, workflow_status, created_at, updated_at, deleted_at |
| threads | id (= canonical thread_id), project_id, title, status, last_activity_at, created_at, archived_at; отдельный checkpoint namespace на чат |
| pending_commands | id, thread_id, run_id NULL, client_request_id, sequence, message_jsonb, status, received_at, applied_at, checkpoint_ref; UNIQUE(thread_id, client_request_id) |
| message_attachments | thread_id, message_id, ref_kind, resource_id, resource_version, locator_jsonb; immutable ссылка на документ/артефакт |
| skill_invocations | id, thread_id, run_id, skill_id, skill_version, source_commit, status, parent_tool_call_id, input_refs, output_refs, timestamps |
| project_companies | project_id, company_id, report_id, role, shortlisted, added_at, removed_at; UNIQUE активной пары |
| project_facts | id, project_id, key, value_jsonb, unit, currency, company_id NULL, provenance_ref, confirmation_status, version, supersedes_id |
| documents | id, project_id, company_id NULL, filename, mime, size, storage_key, hash, parsing_status, error_code, uploaded_by, created_at, deleted_at |
| document_fragments | id, document_id, locator_jsonb, page NULL, text, offsets/bbox NULL, extraction_method, extraction_status |
| open_questions | id, project_id, company_id NULL, question, reason, status, evidence_refs, resolved_by_ref, version |
| artifacts | id, project_id, kind, version, based_on_context_version, report_ids, content_jsonb, evidence_refs, author_run_id, source_thread_id, freshness_status |
| decisions | id, project_id, author_user_id, company_ids, outcome, rationale, conditions, evidence_refs, based_on_artifact_id/version, context_version, created_at, supersedes_id |
| runs | id, project_id, thread_id, client_request_id, state, started_at, finished_at, based_on_context_version, model_id, usage_jsonb, safe_error, checkpoint_ref |
| conversation_views | thread_id, revision, public_state_jsonb, updated_at; производная UI-проекция, не второй механизм graph memory |
| activity_log | run_id, ordinal, kind, public_label, status, evidence_refs, timestamps; нет сырого chain-of-thought |
| framework-owned checkpoint / store tables | Штатные таблицы LangGraph; не собственные ORM-копии и не ручная сериализация checkpoint |

В версии 1.1 проект содержит несколько threads, каждый виден на UI как отдельный чат/сессия. Полная история и checkpoints разделены, общий контекст проекта — только условия, документы и явно выбранные артефакты. Долговременные предпочтения между проектами не извлекать автоматически. Подтверждённые условия принадлежат прикладной модели; Store не должен незаметно стать второй противоречащей копией этих условий.

## 5. Импорт и валидация

1. Вычислить sha256 и batch ID, проверить корневой формат, сохранить сведения об источнике.
2. Преобразовать Mongo Extended JSON (`$date`, `$numberLong`, `_id`) без потери идентичности и точности.
3. Сохранить снимок и нормализовать секции. Числовые строки разбирать в Decimal; malformed значения оставлять недоступными с warning, не как ноль.
4. Для каждого поля/раздела фиксировать наличие, пустоту и ошибки. `{}` в агрегате не всегда означает подтверждённый count=0.
5. Вставить company и report, дочерние строки и доступность атомарно на снимок. При ошибке нормализации сохранить raw/diagnostic с явным partial/invalid ingestion status, не выдавать его как полный.
6. Идемпотентность: повтор того же snapshot hash не создаёт новую версию или дубликаты дочерних записей. Изменённый snapshot — новая версия.
7. Сформировать отчёт импорта: число записей, непустые секции, неизвестные поля, ошибки, пропуски, периоды. Импорт — CLI/job, не endpoint агента.

ИНН хранить строкой; проверка формата/контрольной суммы не должна молча выбрасывать учебные записи. Несоответствие фиксируется в отчёте импорта, применение к поиску согласуется с fixture. Поиск нового ИНН в UI проходит валидацию, а не «находит» несуществующие данные.

## 6. Индексы и удаление

Индексы: companies.inn; report_snapshots(company_id, source_report_at); financial_statements(report_id, year); execution_proceedings(report_id, active, started_at); все внешние ключи; projects(tenant_id, updated_at); runs(thread_id, state), UNIQUE(thread_id, client_request_id); документы и артефакты по project_id. Для запроса активного run предусмотреть уникальность одного активного исполнения на thread (не одного сообщения) средствами транзакции/индекса и корректное снятие после завершения.

Удаление компании из проекта не удаляет исходный report; историческая ссылка остаётся отмеченной. Удаление документа убирает доступ к байтам и фрагментам, а зависимые выводы получают пометку об удалённом основании. Удаление проекта очищает его файлы, проекции, checkpoints и память через поддерживаемые API; очищение внешних логов/backup описывается в операционной политике и не обещается мгновенным. Активный run сначала отменяется, новые записи в удалённый проект запрещены.

## 7. Проверки приёмки

- Импортируются 100 исходных объектов; повторный запуск не удваивает строки.
- Различаются отсутствующие финансы, пустой раздел, ноль и ошибка числа.
- Финансы, производства и лицензии доступны с report_id и source_path.
- Агрегат арбитража нигде не становится выдуманным отдельным делом.
- Уставный капитал, капитал отчётности и итог пассива не перепутаны.
- Разные tenants не получают проекты/файлы друг друга.
- Удаление проекта не затрагивает общий набор отчётов.

## 8. Точные ключи статусных агрегатов арбитража

Все пути ниже относительно `report.arbitrationByStatus`. Опечатку `defandantArbitration` учитывать в parser, наружу публиковать role=`defendant`.

| Роль / статус | Вложенный объект | Количество / сумма |
|---|---|---|
| plaintiff / finished | plaintiffArbitration.plaintiffArbitrationFinished | pfCount / pfAmount |
| plaintiff / appealed | plaintiffArbitration.plaintiffArbitrationAppealed | paCount / paAmount |
| plaintiff / pending | plaintiffArbitration.plaintiffArbitrationPending | ppCount / ppAmount |
| defendant / finished | defandantArbitration.defandantArbitrationFinished | dfCount / dfAmount |
| defendant / appealed | defandantArbitration.defandantArbitrationAppealed | daCount / daAmount |
| defendant / pending | defandantArbitration.defandantArbitrationPending | dpCount / dpAmount |

commonCount/commonAmount хранятся отдельно как предоставленные итоги. Не складывать их с детализацией и годовыми агрегатами. Пустые объекты статусов сохраняют present_empty без автоматически достроенного count=0, если семантика не подтверждена.

## 9. Дополнение 1.1: источники офисных файлов и команды

Document locator — discriminated union: pdf_page; spreadsheet_range (sheet, range, cell); word_block (paragraph_id/table_id/row/cell); text_lines. Для DOCX без layout-rendering номер страницы неизвестен. Для XLSX сохранять координаты, пустые строки/колонки, формулу отдельно от cached_value и статус кэша. Сам файл остаётся immutable; производный текст не заменяет original.

ArtifactRef: artifact_id + version + optional section. Прикрепление не копирует целый артефакт в каждое сообщение; версия закрепляется. Если исходник удалён, ref остаётся в истории с unavailable status. Артефакт одного чата может использовать другой только внутри разрешённого проекта. source_thread_id обозначает происхождение, не ограничивает всю видимость автором-чата.

pending_commands.status: accepted → queued → applying → applied; отмена до применения — cancelled, ошибка — failed. Применение к graph state идемпотентно по message_id; после сбоя флаг применения сверяется с checkpoint, чтобы не повторить сообщение. Архивирование thread не удаляет артефакты проекта. Удаление thread требует удаления его checkpoints/messages/inbox и пометки ссылок; проектные документы не удалять каскадом вместе с одним чатом.
