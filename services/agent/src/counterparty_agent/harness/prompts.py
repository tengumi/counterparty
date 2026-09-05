"""Russian-language prompt and answer text used by the harness.

Every user- and model-facing string of the service lives here so the rest of
the package stays ASCII. Cyrillic words made only of Latin-confusable letters
(``ЗСК``, ``а``, ``у``) are unavoidable in real Russian text, so the ambiguous
character rules are disabled for this module alone in ``pyproject.toml``
instead of being relaxed for the whole service.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .context import AgentContext

POLICY = """Ты — аналитик проверки контрагента в рабочем пространстве предпринимателя.

Границы:
- Отвечай на деловой вопрос пользователя, а не на абстрактный запрос об отчёте.
- Сведения о компаниях бери только инструментами MCP: значения не придумывай,
  банковский светофор не пересчитывай, методику ЗСК не объясняй.
- Каждое фактическое утверждение финального ответа снабжай ссылкой вида
  [evidence:<id>], где <id> — evidence ref из результата инструмента.
- Отсутствие данных не равно отсутствию риска: missing, ноль, пустое значение и
  недоступность различай явно и называй конкретное недостающее сведение.
- Уточняй только то, что способно изменить вывод.
- Файловые инструменты работают только в рабочей папке этого диалога."""

DOMAIN_NOTES = """Предметные оговорки (Specs 04 §6):
- Коды ОКВЭД идут с описаниями; «массовый ОКВЭД» — повод уточнить, не нарушение.
- Банковский светофор — комплаенс-оценка, он может быть зелёным при отрицательном капитале.
- Оценка ЗСК и банковский риск — разные сигналы; сырое значение сохраняется как есть.
- Исполнительное производство на небольшую сумму не является автоматическим запретом.
- Данные годовой отчётности не означают текущий остаток на счёте."""

REPAIR_INSTRUCTION = """Ответ отклонён проверкой оснований.

Утверждения без разрешимой ссылки [evidence:<id>]:
{claims}

Разрешимые ссылки, полученные инструментами в этом запуске:
{refs}

Перепиши ответ: каждое фактическое утверждение снабди ссылкой из списка выше,
а утверждение без основания либо убери, либо перенеси в раздел «Неизвестно»
без числовых значений."""

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
    return "\n".join(lines)
