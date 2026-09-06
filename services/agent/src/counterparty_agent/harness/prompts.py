"""Russian-language prompt and answer text used by the harness.

Every user- and model-facing string of the service lives here so the rest of
the package stays ASCII. Cyrillic words made only of Latin-confusable letters
(``ЗСК``, ``а``, ``у``) are unavoidable in real Russian text, so the ambiguous
character rules are disabled for this module alone in ``pyproject.toml``
instead of being relaxed for the whole service.
"""

from typing import TYPE_CHECKING

from .knowledge import render_reference

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import AgentContext

POLICY = """Ты — аналитик проверки контрагента в рабочем пространстве предпринимателя.

Границы:
- Отвечай на деловой вопрос пользователя, а не на абстрактный запрос об отчёте.
- Сведения о компаниях бери только инструментами MCP: значения не придумывай,
  банковский светофор не пересчитывай, методику ЗСК не объясняй.
- Каждое фактическое утверждение финального ответа снабжай ссылкой вида
  [evidence:<id>], где <id> — evidence ref из результата инструмента.
- Отвечай кратко: вывод, 3–5 ключевых оснований, затем «Неизвестно» и
  следующий вопрос. Одно основание — один пункт со ссылкой до конечной точки.
- Денежные значения воспроизводи в единицах, выданных инструментом. Не
  пересчитывай их в тысячи/миллионы, не вычисляй отношения самостоятельно.
- Не сравнивай деньги компании с суммой аванса, если сумма сделки неизвестна.
- Отсутствие данных не равно отсутствию риска: missing, ноль, пустое значение и
  недоступность различай явно и называй конкретное недостающее сведение.
- Уточняй только то, что способно изменить вывод.
- Файловые инструменты работают только в рабочей папке этого диалога."""

DOMAIN_NOTES = render_reference()
"""Standing domain notes, generated from the versioned reference in
:mod:`counterparty_agent.harness.knowledge` so provenance and tests stay
attached. A question also pulls the fragments it touches through
``knowledge.lookup`` and they are rendered by :func:`render_system_prompt`."""

REPAIR_INSTRUCTION = """Ответ отклонён проверкой оснований.

Утверждения без разрешимой ссылки [evidence:<id>]:
{claims}

Разрешимые ссылки, полученные инструментами в этом запуске:
{refs}

Перепиши ответ: каждое фактическое утверждение снабди ссылкой из списка выше,
а утверждение без основания либо убери, либо перенеси в раздел «Неизвестно»
без числовых значений."""

ACTIVITY_READING_REPORT = "Читаю закреплённый отчёт"
ACTIVITY_CHECKING_CONTEXT = "Проверен состав проверки"
ASK_TO_ADD_COMPANY = (
    "В этой проверке ещё нет закреплённой компании. Нажмите «Добавить» "
    "над разговором, введите ИНН и добавьте компанию. Затем отправьте вопрос снова — "
    "я смогу разобрать её отчёт со ссылками на основания."
)
RUN_FAILED_MESSAGE = "Не удалось завершить разбор. Попробуйте повторить запрос."
ANSWER_HEADING = "Что показывает закреплённый отчёт:"
ASK_FOR_INN = "Назовите ИНН компании, тогда я подниму закреплённый отчёт и отвечу по нему?"
MISSING_SECTION_LINE = (
    "- Раздел {section} в снимке отсутствует ({state}), это не подтверждённый ноль."
)
UNKNOWN_HEADING = "Неизвестно:"
"""Heading the repair pass writes its notes under."""

UNVERIFIED_DROPPED = (
    "Часть утверждений исключена из ответа: у них нет разрешимой ссылки на источник."
)
UNVERIFIED_FALLBACK = "Подтверждённых оснований для вывода пока нет, нужны дополнительные сведения."
UNKNOWN_HEADINGS: frozenset[str] = frozenset(
    {"неизвестно", "нужно уточнить", "вопросы", "следующий шаг", "следующие шаги"}
)
"""Headings whose non-numeric lines may state a gap without citing a source."""


def render_system_prompt(context: "AgentContext") -> str:
    """Render the layered system prompt, each layer naming its authority."""
    project = context.project
    lines = [
        POLICY,
        "",
        context.domain_notes,
        "",
        f"## Проект (workspace, версия контекста {project.context_version})",
        f"- Название: {project.title}",
        f"- Статус: {project.workflow_status}",
    ]
    if project.companies:
        lines.append("- Компании проекта (report_id закреплён снимком):")
        lines.extend(
            f"  - слот {company.slot}: роль {company.role}, "
            f"company_id={company.company_id}, report_id={company.report_id}"
            + (f", ИНН {company.inn}" if company.inn else "")
            for company in project.companies
        )
    else:
        lines.append("- Компании ещё не закреплены, ИНН уточняется у пользователя.")
    lines.extend(
        [
            "",
            "## Диалог",
            f"- Рабочая сессия: {context.thread.title} ({context.thread.status})",
            "- История других чатов этого проекта недоступна и не подмешивается.",
            f"- Рабочая папка диалога: {context.workspace_root}",
        ]
    )
    if context.relevant_notes:
        lines.extend(["", context.relevant_notes])
    return "\n".join(lines)
