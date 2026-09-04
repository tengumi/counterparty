"""Канонические контракты загрузки и разрешения контрагентов."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class PartyType(StrEnum):
    """Тип субъекта, определяемый по проверенным идентификаторам."""

    LEGAL_ENTITY = "LEGAL_ENTITY"
    INDIVIDUAL_ENTREPRENEUR = "INDIVIDUAL_ENTREPRENEUR"


class BankTrafficLight(StrEnum):
    """Отображаемые значения внешнего банковского светофора."""

    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    GREY = "GREY"


class SourceOutcome(StrEnum):
    """Результат обращения к источнику данных."""

    SUCCESS = "success"
    EMPTY = "empty"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    DENIED = "denied"
    INVALID = "invalid"


class ResolutionStatus(StrEnum):
    """Результат разрешения одного упоминания контрагента."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NEEDS_CONFIRMATION = "needs_confirmation"
    NOT_FOUND = "not_found"
    INVALID_IDENTIFIER = "invalid_identifier"


class MatchMethod(StrEnum):
    """Способ, которым найден кандидат."""

    INN_EXACT = "inn_exact"
    OGRN_EXACT = "ogrn_exact"
    NAME_EXACT = "name_exact"
    NAME_FUZZY = "name_fuzzy"


class QueryIntent(StrEnum):
    """Минимальные намерения, которые распознаются без языковой модели."""

    LOOKUP = "lookup"
    COMPARE_EXPLICIT = "compare_explicit"


class EntityKind(StrEnum):
    """Тип сущности, явно извлечённой из пользовательского запроса."""

    INN = "inn"
    OGRN = "ogrn"
    NAME = "name"


class EvidenceKind(StrEnum):
    """Происхождение факта без смешивания наблюдения и расчёта."""

    OBSERVED = "observed"
    PROVIDER_ASSERTION = "provider_assertion"
    DERIVED = "derived"
    DATA_GAP = "data_gap"


class EvidenceQuality(StrEnum):
    """Качество извлечения; confirmed не подтверждает истинность у поставщика."""

    CONFIRMED = "confirmed"
    PARTIAL = "partial"
    CONFLICTING = "conflicting"


class EvidenceCoverage(StrEnum):
    """Наличие поля в исходном отчёте."""

    PRESENT = "present"
    EMPTY = "empty"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class PiiClass(StrEnum):
    """Класс чувствительности для последующей фильтрации контекста и логов."""

    NONE = "none"
    ORGANIZATION = "organization"
    CONTACT = "contact"
    PERSON = "person"


class ReputationPolarity(StrEnum):
    """Раздел исходного репутационного сигнала."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class CompanyIdentity(BaseModel):
    """Минимальные реквизиты для идентификации компании или ИП."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    inn: str = Field(pattern=r"^(?:\d{10}|\d{12})$")
    ogrn: str = Field(pattern=r"^(?:\d{13}|\d{15})$")
    kpp: str | None = Field(default=None, pattern=r"^\d{9}$")
    full_name: str = Field(min_length=1)
    short_name: str = Field(min_length=1)
    party_type: PartyType
    address: str | None = None
    registration_at: AwareDatetime
    okpo: str | None = None
    email: str | None = None
    website: str | None = None
    company_size: str | None = None


class FinancialAssets(BaseModel):
    """Активы за один отчётный год; пропуски не подменяются нулями."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: Decimal
    current_total: Decimal | None = None
    stocks: Decimal | None = None
    receivables: Decimal | None = None
    cash_and_equivalents: Decimal | None = None
    non_current_total: Decimal | None = None
    fixed_assets: Decimal | None = None


class FinancialLiabilities(BaseModel):
    """Пассивы за один отчётный год в единицах исходного отчёта."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: Decimal
    capital_and_reserves: Decimal | None = None
    long_term_total: Decimal | None = None
    other_long_term: Decimal | None = None
    short_term_total: Decimal | None = None
    borrowed_funds: Decimal | None = None
    accounts_payable: Decimal | None = None


class FinancialStatement(BaseModel):
    """Канонический бухгалтерский отчёт за один год."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int = Field(ge=1900, le=2200)
    proceeds: Decimal | None = None
    profit: Decimal | None = None
    assets: FinancialAssets
    liabilities: FinancialLiabilities


class FinancialCoefficients(BaseModel):
    """Готовые коэффициенты источника без предположений об их единицах."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int = Field(ge=1900, le=2200)
    profitability: Decimal
    solvency: Decimal
    sustainability: Decimal


class ArbitrationRoleSummary(BaseModel):
    """Агрегаты дел для одной процессуальной роли."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finished_count: int | None = Field(default=None, ge=0)
    finished_amount: Decimal | None = None
    pending_count: int | None = Field(default=None, ge=0)
    pending_amount: Decimal | None = None
    appealed_count: int | None = Field(default=None, ge=0)
    appealed_amount: Decimal | None = None


class ArbitrationSummary(BaseModel):
    """Сводные данные арбитража на дату отчёта."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_count: int | None = Field(default=None, ge=0)
    total_amount: Decimal | None = None
    as_plaintiff: ArbitrationRoleSummary
    as_defendant: ArbitrationRoleSummary


class ArbitrationYearSummary(BaseModel):
    """Годовой агрегат участия в арбитражных делах."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    year: int = Field(ge=1900, le=2200)
    plaintiff_count: int = Field(ge=0)
    plaintiff_amount: Decimal
    defendant_count: int = Field(ge=0)
    defendant_amount: Decimal


class EnforcementProceeding(BaseModel):
    """Исполнительное производство без интерпретации его значимости."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: str
    opened_at: AwareDatetime
    is_active: bool
    amount: Decimal | None = None


class EconomicActivity(BaseModel):
    """Вид экономической деятельности с исходным кодом."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    description: str


class ActivityProfile(BaseModel):
    """Основной и дополнительные виды деятельности."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    main: EconomicActivity
    others: tuple[EconomicActivity, ...] | None


class LicenseRecord(BaseModel):
    """Лицензия с неизменённым статусом источника."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    number: str
    name: str
    raw_status: str
    issued_at: AwareDatetime
    ends_at: AwareDatetime | None = None
    issuing_authority: str


class ReputationSignal(BaseModel):
    """Готовый репутационный сигнал поставщика данных."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_code: str
    canonical_code: str
    name: str
    chapter: str
    polarity: ReputationPolarity


class ReputationProfile(BaseModel):
    """Положительные и отрицательные сигналы хранятся раздельно."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    positive: tuple[ReputationSignal, ...]
    negative: tuple[ReputationSignal, ...]


class Evidence(BaseModel):
    """Проверяемая привязка канонического факта к полю исходного snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["evidence-v1"] = "evidence-v1"
    evidence_id: str = Field(pattern=r"^evidence_[0-9a-f]{24}$")
    company_id: str = Field(pattern=r"^company_[0-9a-f]{24}$")
    snapshot_id: str = Field(pattern=r"^snapshot_[0-9a-f]{24}$")
    canonical_path: str = Field(min_length=1)
    stable_key: str = Field(min_length=1)
    source_paths: tuple[str, ...] = Field(min_length=1)
    kind: EvidenceKind
    typed_value: Any = Field(repr=False, exclude=True)
    report_at: AwareDatetime
    source_name: str
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    unit: str | None = None
    currency: str | None = None
    period: int | str | None = None
    quality: EvidenceQuality = EvidenceQuality.CONFIRMED
    coverage: EvidenceCoverage = EvidenceCoverage.PRESENT
    pii_class: PiiClass = PiiClass.NONE
    derived_from: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_lineage(self) -> Self:
        """Проверить locator исходного поля и lineage производного факта."""

        if any(not path.startswith("/") for path in self.source_paths):
            raise ValueError("Пути evidence должны быть JSON Pointer")
        if self.kind is EvidenceKind.DERIVED and not self.derived_from:
            raise ValueError("Производный evidence должен ссылаться на исходные evidence")
        return self


class CompanyStatus(BaseModel):
    """Статус субъекта без интерпретации неизвестных значений источника."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_status: str
    effective_at: AwareDatetime
    reason: str | None = None


class BankRiskAssessment(BaseModel):
    """Неизменяемый внешний банковский сигнал закрытой методологии."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_level: str | None
    recognized_level: BankTrafficLight | None
    display_level: BankTrafficLight
    assessed_at: AwareDatetime
    source: Literal["bank_scoring"] = "bank_scoring"
    methodology_disclosed: Literal[False] = False

    @model_validator(mode="after")
    def validate_display_level(self) -> Self:
        """Не позволить интерфейсу изменить распознанный банковский цвет."""

        try:
            expected_recognized = (
                BankTrafficLight(self.raw_level) if self.raw_level is not None else None
            )
        except ValueError:
            expected_recognized = None
        if self.recognized_level != expected_recognized:
            raise ValueError("Распознанный светофор не совпадает с исходным сигналом")
        expected_display = expected_recognized or BankTrafficLight.GREY
        if self.display_level != expected_display:
            raise ValueError("Отображаемый светофор не совпадает с исходным сигналом")
        return self


class CounterpartySnapshot(BaseModel):
    """Канонический снимок с полным нормализованным отчётом источника."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["counterparty-snapshot-v1"] = "counterparty-snapshot-v1"
    company_id: str = Field(pattern=r"^company_[0-9a-f]{24}$")
    snapshot_id: str = Field(pattern=r"^snapshot_[0-9a-f]{24}$")
    report_at: AwareDatetime
    source_name: str
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    identity: CompanyIdentity
    status: CompanyStatus
    bank_risk: BankRiskAssessment
    base_risk_level_raw: str | None = None
    financial_statements: tuple[FinancialStatement, ...] | None
    financial_coefficients: FinancialCoefficients | None
    arbitration_summary: ArbitrationSummary
    arbitration_by_year: tuple[ArbitrationYearSummary, ...] | None
    enforcement_proceedings: tuple[EnforcementProceeding, ...]
    activities: ActivityProfile
    licenses: tuple[LicenseRecord, ...] | None
    reputation: ReputationProfile
    evidence: tuple[Evidence, ...] = Field(repr=False, exclude=True)
    report: dict[str, Any] = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> Self:
        """Гарантировать уникальность доказательств внутри одного снимка."""

        evidence_ids = tuple(item.evidence_id for item in self.evidence)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Идентификаторы evidence должны быть уникальными")
        if any(item.snapshot_id != self.snapshot_id for item in self.evidence):
            raise ValueError("Все evidence должны относиться к текущему snapshot")
        if any(item.company_id != self.company_id for item in self.evidence):
            raise ValueError("Все evidence должны относиться к текущей компании")
        if any(item.source_hash != self.source_hash for item in self.evidence):
            raise ValueError("Все evidence должны относиться к текущему источнику")
        if any(item.record_hash != self.record_hash for item in self.evidence):
            raise ValueError("Все evidence должны относиться к текущей записи")
        if any(item.source_name != self.source_name for item in self.evidence):
            raise ValueError("Все evidence должны содержать имя текущего источника")
        if any(item.report_at != self.report_at for item in self.evidence):
            raise ValueError("Все evidence должны содержать дату текущего отчёта")
        return self


class CounterpartyCandidate(BaseModel):
    """Безопасное краткое представление кандидата для выбора пользователем."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    company_id: str = Field(pattern=r"^company_[0-9a-f]{24}$")
    snapshot_id: str = Field(pattern=r"^snapshot_[0-9a-f]{24}$")
    inn: str = Field(pattern=r"^(?:\d{10}|\d{12})$", repr=False)
    ogrn: str = Field(pattern=r"^(?:\d{13}|\d{15})$", repr=False)
    full_name: str = Field(min_length=1, repr=False)
    short_name: str = Field(min_length=1, repr=False)
    party_type: PartyType
    raw_status: str
    match_score: float | None = Field(default=None, ge=0, le=100)
    rank: int | None = Field(default=None, ge=1)
    legal_form_conflict: bool = False


class ResolutionResult(BaseModel):
    """Типизированный результат точного поиска одного контрагента."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["resolution-result-v1"] = "resolution-result-v1"
    status: ResolutionStatus
    query: str = Field(repr=False)
    method: MatchMethod | None = None
    candidates: tuple[CounterpartyCandidate, ...] = ()

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        """Не допустить противоречивое сочетание статуса и кандидатов."""

        candidate_count = len(self.candidates)
        if self.status is ResolutionStatus.RESOLVED and candidate_count != 1:
            raise ValueError("Для статуса resolved нужен ровно один кандидат")
        if self.status is ResolutionStatus.AMBIGUOUS and candidate_count < 2:
            raise ValueError("Для статуса ambiguous нужны минимум два кандидата")
        if self.status is ResolutionStatus.NEEDS_CONFIRMATION and candidate_count < 1:
            raise ValueError("Для fuzzy-уточнения нужен хотя бы один кандидат")
        if (
            self.status
            in {
                ResolutionStatus.NOT_FOUND,
                ResolutionStatus.INVALID_IDENTIFIER,
            }
            and candidate_count
        ):
            raise ValueError("Для результата без совпадений список кандидатов должен быть пуст")
        if candidate_count and self.method is None:
            raise ValueError("Для найденных кандидатов должен быть указан способ поиска")
        if self.method is MatchMethod.NAME_FUZZY:
            if self.status is not ResolutionStatus.NEEDS_CONFIRMATION:
                raise ValueError("Fuzzy-поиск не может автоматически выбрать компанию")
            if any(
                candidate.match_score is None or candidate.rank != rank
                for rank, candidate in enumerate(self.candidates, start=1)
            ):
                raise ValueError("Fuzzy-кандидаты должны иметь score и последовательный rank")
        return self


class EntityMention(BaseModel):
    """Одно упоминание компании или её идентификатора в запросе."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mention_id: str = Field(pattern=r"^mention_[1-9]\d*$")
    kind: EntityKind
    raw_text: str = Field(min_length=1, repr=False, exclude=True)
    normalized_value: str = Field(min_length=1, repr=False)
    checksum_valid: bool | None = None
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=1)
    explicit: bool

    @model_validator(mode="after")
    def validate_checksum_state(self) -> Self:
        """Контрольная сумма применима только к ИНН и ОГРН."""

        if self.kind is EntityKind.NAME and self.checksum_valid is not None:
            raise ValueError("Для названия нельзя задавать контрольную сумму")
        if self.kind is not EntityKind.NAME and self.checksum_valid is None:
            raise ValueError("Для идентификатора нужен результат проверки контрольной суммы")
        if self.span_end <= self.span_start:
            raise ValueError("Конец span должен находиться после начала")
        return self


class QueryPlan(BaseModel):
    """Детерминированный план разрешения сущностей одного запроса."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["query-plan-v1"] = "query-plan-v1"
    raw_query: str = Field(min_length=1, repr=False, exclude=True)
    intent: QueryIntent
    mentions: tuple[EntityMention, ...]

    @model_validator(mode="after")
    def validate_mentions(self) -> Self:
        """Не допустить повторных идентификаторов упоминаний."""

        mention_ids = tuple(mention.mention_id for mention in self.mentions)
        if len(mention_ids) != len(set(mention_ids)):
            raise ValueError("Идентификаторы упоминаний должны быть уникальными")
        return self


class QueryResolution(BaseModel):
    """Результат поиска всех сущностей с явным признаком уточнения."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["query-resolution-v1"] = "query-resolution-v1"
    plan: QueryPlan
    results: tuple[ResolutionResult, ...]
    resolved_company_ids: tuple[str, ...]
    requires_clarification: bool

    @model_validator(mode="after")
    def validate_resolution(self) -> Self:
        """Сверить результаты с планом и разрешёнными компаниями."""

        if len(self.results) != len(self.plan.mentions):
            raise ValueError("Каждому упоминанию должен соответствовать результат")
        for mention, result in zip(self.plan.mentions, self.results, strict=True):
            if result.query != mention.normalized_value:
                raise ValueError("Результат относится к другому упоминанию")
            if mention.kind is EntityKind.NAME:
                if result.status is ResolutionStatus.INVALID_IDENTIFIER:
                    raise ValueError("Название не может иметь ошибку контрольной суммы")
                if result.method not in {None, MatchMethod.NAME_EXACT, MatchMethod.NAME_FUZZY}:
                    raise ValueError("Название разрешено несовместимым способом")
            elif mention.kind is EntityKind.INN and result.method not in {
                None,
                MatchMethod.INN_EXACT,
            }:
                raise ValueError("ИНН разрешён несовместимым способом")
            elif mention.kind is EntityKind.OGRN and result.method not in {
                None,
                MatchMethod.OGRN_EXACT,
            }:
                raise ValueError("ОГРН разрешён несовместимым способом")
        expected_ids = tuple(
            result.candidates[0].company_id
            for result in self.results
            if result.status is ResolutionStatus.RESOLVED
        )
        expected_ids = tuple(dict.fromkeys(expected_ids))
        if self.resolved_company_ids != expected_ids:
            raise ValueError("Список разрешённых компаний не соответствует результатам")
        expected_clarification = (
            not self.plan.mentions
            or any(result.status is not ResolutionStatus.RESOLVED for result in self.results)
            or (
                self.plan.intent is QueryIntent.COMPARE_EXPLICIT
                and len(self.resolved_company_ids) < 2
            )
        )
        if self.requires_clarification is not expected_clarification:
            raise ValueError("Признак уточнения не соответствует результатам")
        return self


class FindingCategory(StrEnum):
    """Тема вывода, независимая от банковского светофора."""

    COMPANY = "company"
    FINANCE = "finance"
    ARBITRATION = "arbitration"
    ENFORCEMENT = "enforcement"
    REPUTATION = "reputation"
    DATA_QUALITY = "data_quality"


class FindingSeverity(StrEnum):
    """Приоритет просмотра факта, а не новая оценка надёжности."""

    INFO = "info"
    ATTENTION = "attention"


class FindingDataStatus(StrEnum):
    """Полнота основания вывода; confirmed относится только к входному отчёту."""

    CONFIRMED = "confirmed"
    PARTIAL = "partial"
    CONFLICTING = "conflicting"
    INSUFFICIENT = "insufficient"
    INAPPLICABLE = "inapplicable"


class AnalysisPolicy(BaseModel):
    """Явные настройки анализа: норматив давности по умолчанию не выдумывается."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_report_age_days: int | None = Field(default=None, ge=0)


class Finding(BaseModel):
    """Воспроизводимый факт, сигнал или пробел со ссылками на доказательства."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_id: str = Field(pattern=r"^finding_[0-9a-f]{24}$")
    company_id: str = Field(pattern=r"^company_[0-9a-f]{24}$")
    snapshot_id: str = Field(pattern=r"^snapshot_[0-9a-f]{24}$")
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    category: FindingCategory
    severity: FindingSeverity
    data_status: FindingDataStatus
    statement: str = Field(min_length=1, repr=False)
    period: int | str | None = None
    evidence_ids: tuple[str, ...] = Field(min_length=1)


class AnalysisResult(BaseModel):
    """Компактные выводы одной карточки; полный ledger не отправляется автоматически."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["analysis-result-v1"] = "analysis-result-v1"
    rules_version: Literal["analysis-rules-v1"] = "analysis-rules-v1"
    company_id: str = Field(pattern=r"^company_[0-9a-f]{24}$")
    snapshot_id: str = Field(pattern=r"^snapshot_[0-9a-f]{24}$")
    report_at: AwareDatetime
    evaluated_at: AwareDatetime
    policy: AnalysisPolicy
    bank_risk: BankRiskAssessment
    bank_evidence_id: str = Field(pattern=r"^evidence_[0-9a-f]{24}$")
    findings: tuple[Finding, ...]
    derived_evidence: tuple[Evidence, ...] = Field(repr=False, exclude=True)

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        """Проверить уникальность и область локальных артефактов анализа."""

        for items, id_field in (
            (self.findings, "finding_id"),
            (self.derived_evidence, "evidence_id"),
        ):
            identifiers = [getattr(item, id_field) for item in items]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("Артефакты анализа должны иметь уникальные идентификаторы")
            if any(
                item.company_id != self.company_id or item.snapshot_id != self.snapshot_id
                for item in items
            ):
                raise ValueError("Артефакт анализа относится к другой компании или снимку")
        return self


class ComparisonCell(BaseModel):
    """Значение одной компании с доказательствами; пропуск не подменяется нулём."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(pattern=r"^snapshot_[0-9a-f]{24}$")
    display_value: str = Field(min_length=1, repr=False)
    value: str | int | None = Field(repr=False)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    data_status: FindingDataStatus


class ComparisonRow(BaseModel):
    """Одинаковый показатель для выбранных компаний, без скрытого ранжирования."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1)
    category: str = Field(min_length=1)
    period: int | None = Field(default=None, ge=1900, le=2200)
    comparable: bool
    comparison_note: str = Field(min_length=1)
    cells: tuple[ComparisonCell, ...] = Field(min_length=2)


class ComparisonResult(BaseModel):
    """Проверенная матрица явно выбранных компаний без нового общего скоринга."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_ids: tuple[str, ...] = Field(min_length=2)
    evaluated_at: AwareDatetime
    financial_year: int | None = Field(default=None, ge=1900, le=2200)
    rows: tuple[ComparisonRow, ...] = Field(min_length=1)
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_matrix(self) -> Self:
        """Зафиксировать уникальные столбцы и единый порядок во всех строках."""

        if len(set(self.snapshot_ids)) != len(self.snapshot_ids):
            raise ValueError("Компания повторяется в матрице сравнения")
        if len({row.key for row in self.rows}) != len(self.rows):
            raise ValueError("Показатель повторяется в матрице сравнения")
        if any(
            tuple(cell.snapshot_id for cell in row.cells) != self.snapshot_ids for row in self.rows
        ):
            raise ValueError("Порядок ячеек не совпадает с выбранными компаниями")
        return self
