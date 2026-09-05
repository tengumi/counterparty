# Demo runbook — сквозная приёмка MVP-каркаса

Версия 1.0 · 06.09.2026. Тонкий REL-01: один воспроизводимый сценарий по
компании А, границы каркаса и то, что осознанно отложено.

## 1. Что показывает сценарий

Один проход по реальной компании из импортированного корпуса:

1. вход как демо-аналитик, создание проверки, добавление контрагента по ИНН;
2. вопрос агенту → grounded-ответ по закреплённому отчёту: каждая цифра несёт
   разрешимую ссылку `[evidence:report:<snapshot>:/<path>]`, отсутствующие
   разделы названы явно и не выдаются за ноль;
3. lifecycle run'а осел в `workspace.agent_runs` (переживает рестарт агента);
4. решение пользователя записано отдельной версионируемой сущностью с
   собственными условиями и ссылками на источники;
5. `GET …/conversation` честно отражает завершённый run.

## 2. Поднять стек

Нужен Docker. Из корня репозитория:

```sh
docker compose build          # 5 образов (web, ui_api, agent, mcp = 1 образ)
docker compose up -d          # postgres → migrate(0006) → roles → import
                              # → checkpoints → ui_api/mcp → agent → web → proxy
docker compose ps             # шесть долгоживущих сервисов должны быть healthy
```

`migrate`, `roles`, `import`, `checkpoints` — one-shot job'ы: отработали и
вышли. Повторный `up -d` их безопасно перезапускает (import сообщает
`changed_nothing`). Единственный origin для браузера — `http://localhost:5173`.

## 3. Пройти сценарий (компания А = ООО «СПОРТ», ИНН 9705152496)

```sh
BASE=http://localhost:5173/api/v1
CJ=$(mktemp)

# 3.1 сессия демо-аналитика
curl -s -c "$CJ" -X POST "$BASE/auth/session" \
  -H 'content-type: application/json' -d '{"login":"demo-analyst"}' >/dev/null

# 3.2 проверка
PID=$(curl -s -b "$CJ" -X POST "$BASE/projects" -H 'content-type: application/json' \
  -d "{\"title\":\"Приёмка A: ООО СПОРТ\",\"client_request_id\":\"$(uuidgen)\"}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
TID=$(curl -s -b "$CJ" "$BASE/projects/$PID" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["default_thread_id"])')

# 3.3 контрагент по ИНН (новая context_version = 1)
curl -s -b "$CJ" -X POST "$BASE/projects/$PID/companies" -H 'content-type: application/json' \
  -d '{"items":[{"inn":"9705152496"}],"expected_context_version":0}' >/dev/null

# 3.4 grounded-вопрос агенту (стрим SSE через proxy; префикс /agent/ снимается)
curl -s -N http://localhost:5173/agent/rpc/agent/chat -H 'content-type: application/json' \
  -d "{\"project_id\":\"$PID\",\"thread_id\":\"$TID\",\"client_request_id\":\"$(uuidgen)\",\
\"stream\":true,\"commands\":[{\"type\":\"add-message\",\"message\":{\"id\":\"m1\",\
\"text\":\"Контрагент ИНН 9705152496 просит аванс 80%. Что говорят цифры отчётности?\",\
\"document_ids\":[],\"evidence_refs\":[],\"company_ids\":[]}}]}"

# 3.5 решение пользователя (независимая версионируемая сущность)
curl -s -b "$CJ" -X POST "$BASE/projects/$PID/decisions" -H 'content-type: application/json' -d '{
  "outcome":"ready_with_conditions",
  "rationale":"Убыток три года подряд, капитал уходил в минус в 2024.",
  "conditions":["Банковская гарантия на сумму аванса","Поэтапная оплата вместо аванса 80%"],
  "company_ids":[],
  "context_version":1,
  "evidence_refs":["report:<snapshot>:/finReports/2/common/profit"]
}'
```

### Ожидаемый результат

- 3.4: `run.status` доходит до `completed`, `save_status:"saved"`, в тексте —
  строки вида `- Прибыль: -23349000.00 RUB [evidence:report:…:/finReports/2/common/profit]`
  и блок «Неизвестно» с отсутствующими разделами.
- `docker compose exec postgres psql -U counterparty -d counterparty -c
  "SELECT status FROM workspace.agent_runs WHERE thread_id='$TID'"` → `completed`.
- 3.5 → `201`, тело `UserDecision` с `author_user_id` из сессии.
- `GET $BASE/projects/$PID/threads/$TID/conversation` → `run.status:"completed"`,
  `active_run_id:null`, `messages:[]` (см. границу ниже).
- `GET $BASE/projects/$PID/decisions` → список с записанным решением.

### Проверка живучести run'а (AG-04)

```sh
docker compose restart agent
curl -s http://localhost:5173/agent/rpc/agent/runs/<run_id>   # → status из durable строки
```

Прерванный до рестарта run читается как `interrupted`, не «вечно running».

## 4. Границы каркаса (что работает не полностью)

- **Публичная проекция разговора не персистится.** `agent_runs` хранит
  lifecycle; messages/activities живут в памяти процесса агента. `…/conversation`
  и `GET /runs/{id}` после рестарта отдают корректный lifecycle и пустую
  историю сообщений — воспроизведение токенов MVP не требует (Specs 10 §7).
  Полную durable-проекцию добавит отдельная задача.
- **`GET /rpc/agent/runs/{id}` для ещё живущего в памяти run** отдаёт
  `finished_at:null` / `revision:0` (in-memory `_run_info` копирует только
  статус). Durable строка при этом корректна. Косметика, pre-existing.
- **AI-артефакты не создаются.** `analysis_artifacts` и `GET …/artifacts`
  существуют и пусты; решение цитирует `context_version` и `evidence_refs`
  напрямую, без `based_on_artifact_id`. Запись артефактов — AG-05 (post-MVP).
- **Детерминированный provider.** `AGENT_MODEL_PROVIDER=deterministic` —
  scripted tool-calling адаптер (overview → section financials → цитируемые
  строки). Реальную модель подключает пользователь через конфигурацию; её
  готовность не объявляется без прогона.
- **Импортирована только первая вертикаль отчёта:** профиль, статус,
  финансовые периоды, ЗСК, коды деятельности, доступность разделов. Разделы
  arbitration/proceedings/licenses/… доступны через MCP `available_sections`
  как «отсутствует в снимке», но не как записи.
- **Документы, follow-up во время инструментов, upload, сравнение как
  сохранённый artefact, устаревание вывода** — DOC-01…03, AG-05, WEB-10,
  post-MVP.
- **Compose-креды — локальные дефолты.** Ни один не годится для кластера;
  `web` собирается без окружения, агентский MCP-токен не доходит до браузера.

## 5. Свернуть

```sh
docker compose down            # + `-v` чтобы стереть том postgres-data
```
