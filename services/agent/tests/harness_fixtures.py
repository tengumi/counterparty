"""Report fixtures and scripted models shared by the harness tests.

The envelopes are built from the real contract models, so a test that passes
here is a test against the shape the MCP service actually returns.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from counterparty_contracts import (
    Availability,
    BankRiskAssessment,
    CompanyId,
    CompanyIdentity,
    CompanyOverview,
    CompanyOverviewEnvelope,
    CompanyStatusView,
    DisplayLevel,
    FactValue,
    FinancialPeriod,
    McpStatus,
    PageInfo,
    ReportId,
    ReportIdentity,
    ReportSection,
    ReportSectionEnvelope,
    ReportSectionName,
    SectionAvailabilityView,
    ValueType,
    ZskAssessment,
)
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, tool
from pydantic import Field

COMPANY_ID = CompanyId(UUID("11111111-1111-4111-8111-111111111111"))
REPORT_ID = ReportId(UUID("de305d54-75b4-431b-adb2-eb6b9e546014"))
INN = "7449088645"
PROCEEDS_REF = "ev-proceeds-2025"
CAPITAL_REF = "ev-capitals-2025"
STATUS_REF = "ev-status"
_AT = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


def company_overview() -> CompanyOverview:
    """Build an overview whose available facts each name an evidence ref."""
    return CompanyOverview(
        company=CompanyIdentity(id=COMPANY_ID, inn=INN, short_name="Company A"),
        report=ReportIdentity(id=REPORT_ID, source_report_at=_AT, ingested_at=_AT),
        status=CompanyStatusView(
            raw_value="active",
            label="Active",
            availability=Availability.AVAILABLE,
            evidence_refs=[STATUS_REF],
        ),
        bank_risk=BankRiskAssessment(
            raw_value="GREEN",
            label="Green",
            display_level=DisplayLevel.POSITIVE,
            availability=Availability.AVAILABLE,
            evidence_refs=[STATUS_REF],
        ),
        zsk=ZskAssessment(
            raw_value="GREEN",
            display_level=DisplayLevel.POSITIVE,
            policy_version="zsk-display-v1",
            availability=Availability.AVAILABLE,
            evidence_refs=[STATUS_REF],
        ),
        facts=[
            FactValue(
                key="proceeds",
                label="Proceeds",
                value="74586000.00",
                value_type=ValueType.DECIMAL,
                currency="RUB",
                period=2025,
                availability=Availability.AVAILABLE,
                evidence_refs=[PROCEEDS_REF],
            ),
            FactValue(
                key="bankroll",
                label="Bankroll",
                value=None,
                value_type=ValueType.DECIMAL,
                currency="RUB",
                period=2025,
                availability=Availability.MISSING,
            ),
        ],
        available_sections=[
            SectionAvailabilityView(
                section=ReportSectionName.FINANCIALS,
                availability=Availability.AVAILABLE,
                record_count=2,
            ),
            SectionAvailabilityView(
                section=ReportSectionName.LICENSES,
                availability=Availability.MISSING,
            ),
        ],
        rule_version="mcp-read-v1",
    )


def _money(key: str, value: str, ref: str) -> FactValue:
    """Build one available monetary fact with its evidence reference."""
    return FactValue(
        key=key,
        label=key.replace("_", " ").capitalize(),
        value=value,
        value_type=ValueType.DECIMAL,
        currency="RUB",
        period=2025,
        availability=Availability.AVAILABLE,
        evidence_refs=[ref],
    )


def _missing(key: str) -> FactValue:
    """Build one fact the snapshot did not carry; missing is not zero."""
    return FactValue(
        key=key,
        label=key.replace("_", " ").capitalize(),
        value=None,
        value_type=ValueType.DECIMAL,
        currency="RUB",
        period=2025,
        availability=Availability.MISSING,
    )


def financials_section() -> ReportSection:
    """Build one available section with a grounded financial period."""
    return ReportSection(
        report_id=REPORT_ID,
        section=ReportSectionName.FINANCIALS,
        availability=Availability.AVAILABLE,
        records=[
            FinancialPeriod(
                year=2025,
                proceeds=_money("proceeds", "74586000.00", PROCEEDS_REF),
                profit=_missing("profit"),
                total_assets=_missing("total_assets"),
                equity=_money("equity", "-300000.00", CAPITAL_REF),
                cash=_missing("cash"),
                receivables=_missing("receivables"),
                accounts_payable=_missing("accounts_payable"),
                evidence_refs=[PROCEEDS_REF, CAPITAL_REF],
            )
        ],
        facts=[
            FactValue(
                key="capitals",
                label="Capitals",
                value="-300000.00",
                value_type=ValueType.DECIMAL,
                currency="RUB",
                period=2025,
                availability=Availability.AVAILABLE,
                evidence_refs=[CAPITAL_REF],
            )
        ],
        page=PageInfo(limit=20, has_more=False),
        total_records=1,
        rule_version="mcp-read-v1",
    )


def report_tools() -> list[BaseTool]:
    """Return stand-ins for the two accepted MCP tools, same envelopes."""

    @tool
    def get_company_overview(inn: str | None = None, report_id: str | None = None) -> str:
        """Identify one imported company and choose sections to inspect."""
        return CompanyOverviewEnvelope(
            status=McpStatus.OK,
            data=company_overview(),
            source_report_ids=[REPORT_ID],
            rule_version="mcp-read-v1",
        ).model_dump_json()

    @tool
    def get_report_section(report_id: str, section: str) -> str:
        """Inspect facts and sources of one section of a pinned report."""
        return ReportSectionEnvelope(
            status=McpStatus.OK,
            data=financials_section(),
            source_report_ids=[REPORT_ID],
            rule_version="mcp-read-v1",
        ).model_dump_json()

    return [get_company_overview, get_report_section]


class ScriptedChatModel(BaseChatModel):
    """A model that replays a fixed list of assistant messages."""

    script: list[AIMessage] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        """Accept tool binding without inspecting the schemas."""
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        index = min(len(self.calls) - 1, len(self.script) - 1)
        return ChatResult(generations=[ChatGeneration(message=self.script[index])])
