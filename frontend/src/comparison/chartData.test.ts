import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Card, ChatResponse, Evidence, Finding } from "../types";
import {
  annualPoints,
  bankDistribution,
  chartCoordinate,
  exactNumber,
  financialChartPoints,
  financialCoverage,
} from "./chartData";
import { CompanyFinancials } from "./CompanyFinancials";
import { ComparisonOverview } from "./ComparisonOverview";

function card(index = 0): Card {
  const evidence: Evidence = {
    evidence_id: `bank-${index}`,
    canonical_path: "bank_risk",
    source_name: "Проверочный источник",
    report_at: "2026-09-01",
    coverage: "present",
    quality: "confirmed",
  };
  return {
    snapshot_id: `s${index}`,
    name: `Компания ${index}`,
    inn: "",
    ogrn: "",
    report_at: "2026-09-01",
    raw_status: "CURRENT",
    party_type: "LEGAL",
    bank_risk: { raw_level: "GREEN", display_level: "GREEN" },
    bank_evidence_id: evidence.evidence_id,
    evidence: [evidence],
    findings: [],
  };
}
function addYear(target: Card, year: number, proceeds: string | null = "0") {
  const id = `finance-${target.snapshot_id}-${year}`;
  const finding: Finding = {
    finding_id: id,
    code: "financial_period",
    period: year,
    statement: "Годовые значения",
    category: "finance",
    severity: "info",
    data_status: "partial",
    evidence_ids: [id],
  };
  target.findings.push(finding);
  target.evidence.push({
    evidence_id: id,
    canonical_path: "analysis.financial_period",
    source_name: "Проверочный источник",
    report_at: target.report_at,
    coverage: "present",
    quality: "confirmed",
    unit: "source_unit",
    currency: null,
    value: {
      year,
      proceeds,
      profit: null,
      assets_total: "-20.03",
      equity: "0",
    },
  });
}
function response(cards: Card[]): ChatResponse {
  return {
    cards,
    card: null,
    session_id: "s",
    answer: "",
    status: "compared",
    llm_used: false,
    candidates: [],
    comparison_selections: [],
    comparison_pending: false,
    focus_snapshot_id: null,
    answer_claims: [],
    comparison: {
      snapshot_ids: cards.map((item) => item.snapshot_id),
      financial_year: 2025,
      limitations: [],
      rows: [
        {
          key: "financial_proceeds",
          label: "Выручка",
          category: "finance",
          comparable: false,
          comparison_note: "Единицы неизвестны",
          cells: cards.map((item, index) => ({
            snapshot_id: item.snapshot_id,
            value: index ? null : "0",
            display_value: index ? "Нет данных" : "0",
            data_status: index ? "insufficient" : "partial",
            evidence_ids: [item.bank_evidence_id!],
          })),
        },
      ],
    },
  };
}

describe("Финансовые диаграммы", () => {
  it("сохраняет точность исходных строк, ноль, пропуск и отрицательное значение", () => {
    const company = card();
    addYear(company, 2025, "18014398509481985.03");
    addYear(company, 2023);
    const points = annualPoints(company);
    expect(points.map((item) => item.year)).toEqual([2023, 2025]);
    expect(points[1].values.proceeds).toBe("18014398509481985.03");
    expect(points[0].values.profit).toBeNull();
    expect(exactNumber(points[1].values.proceeds)).toBe(
      "18\u202f014\u202f398\u202f509\u202f481\u202f985,03",
    );
    expect(exactNumber(null)).toBe("Нет данных");
    expect(chartCoordinate("0")).toBe(0);
    expect(chartCoordinate(null)).toBeNull();
    expect(chartCoordinate("-20.03")).toBe(-20.03);
    expect(chartCoordinate("1e999")).toBeNull();
    expect(chartCoordinate("1e-999")).toBeNull();
  });
  it("не дорисовывает годы и не включает незавершённый период", () => {
    const company = card();
    addYear(company, 2023);
    addYear(company, 2025);
    addYear(company, 2026);
    expect(annualPoints(company).map((point) => point.year)).toEqual([
      2023, 2025,
    ]);
  });
  it("сохраняет календарный год отчёта на границе часовых поясов", () => {
    const company = card();
    company.report_at = "2026-01-01T00:30:00+03:00";
    addYear(company, 2025);
    expect(annualPoints(company).map((point) => point.year)).toEqual([2025]);
  });
  it("разрывает линию на отсутствующем годе, не создавая фактов и источников", () => {
    const company = card();
    addYear(company, 2025, "-20.03");
    addYear(company, 2023, "0");
    const periods = annualPoints(company);
    expect(financialChartPoints(periods, "proceeds")).toEqual([
      { year: 2023, exact: "0", plot: 0 },
      { year: 2024, exact: null, plot: null },
      { year: 2025, exact: "-20.03", plot: -20.03 },
    ]);
    expect(periods.map((point) => point.year)).toEqual([2023, 2025]);
    const html = renderToStaticMarkup(
      createElement(CompanyFinancials, { card: company, source: () => {} }),
    );
    expect(html).not.toContain("2024");
  });
  it("сохраняет явные пропуски и недоступные для шкалы значения без интерполяции", () => {
    const company = card();
    addYear(company, 2023, "10");
    addYear(company, 2024, null);
    addYear(company, 2025, "1e999");
    const periods = annualPoints(company);
    expect(financialChartPoints(periods, "proceeds")).toEqual([
      { year: 2023, exact: "10", plot: 10 },
      { year: 2024, exact: null, plot: null },
      { year: 2025, exact: "1e999", plot: null },
    ]);
    expect(
      financialChartPoints(periods, "profit").every(
        (point) => point.plot === null,
      ),
    ).toBe(true);
  });
  it("обрабатывает пустой ряд и одну точку без добавления соседних лет", () => {
    expect(financialChartPoints([], "proceeds")).toEqual([]);
    const company = card();
    addYear(company, 2025, "42");
    expect(financialChartPoints(annualPoints(company), "proceeds")).toEqual([
      { year: 2025, exact: "42", plot: 42 },
    ]);
  });
  it("по умолчанию выбирает линию и предоставляет доступный переключатель", () => {
    const company = card();
    addYear(company, 2025, "42");
    const html = renderToStaticMarkup(
      createElement(CompanyFinancials, { card: company, source: () => {} }),
    );
    expect(html).toContain('role="group" aria-label="Тип финансового графика"');
    expect(html).toContain('aria-pressed="true">Линия</button>');
    expect(html).toContain('aria-pressed="false">Столбцы</button>');
    expect(html).toContain('aria-label="Линейная диаграмма: Выручка"');
  });
  it("отклоняет чужое основание, несовпадающий год и дубли периода", () => {
    const company = card();
    addYear(company, 2025);
    company.findings[0].evidence_ids = ["foreign"];
    expect(annualPoints(company)).toEqual([]);
    company.findings[0].evidence_ids = [company.evidence[1].evidence_id];
    company.findings[0].period = 2024;
    expect(annualPoints(company)).toEqual([]);
    company.findings[0].period = 2025;
    addYear(company, 2025);
    expect(annualPoints(company)).toEqual([]);
  });
  it("не извлекает числа из текста модели или небезопасного Number", () => {
    const company = card();
    addYear(company, 2025);
    company.evidence[1].value = {
      year: 2025,
      proceeds: 18014398509481985,
      profit: null,
      assets_total: "0",
      equity: "0",
    };
    expect(annualPoints(company)).toEqual([]);
  });
  it("подписывает ограничения и показывает точные значения без выдуманной валюты", () => {
    const company = card();
    addYear(company, 2025, "123456.78");
    const html = renderToStaticMarkup(
      createElement(CompanyFinancials, { card: company, source: () => {} }),
    );
    expect(html).toContain("Валюта и масштаб сумм не указаны");
    expect(html).toContain("123\u202f456,78");
    expect(html).toContain("Нет данных");
    expect(html).not.toContain("₽");
  });
});
describe("Групповая сводка", () => {
  it("считает всю группу из 100 компаний и разделяет GREY, отсутствие и неизвестный сигнал", () => {
    const cards = Array.from({ length: 100 }, (_, index) => card(index));
    cards[0].bank_risk = { raw_level: "GREY", display_level: "GREY" };
    cards[1].bank_risk = { raw_level: null, display_level: "GREY" };
    cards[2].bank_risk = { raw_level: "OTHER", display_level: "GREY" };
    const segments = bankDistribution(cards);
    expect(segments.map((item) => item.count)).toEqual([97, 0, 0, 1, 1, 1]);
    expect(segments.every((item) => item.verified)).toBe(true);
    expect(segments.find((item) => item.key === "RED")?.evidence).toHaveLength(
      100,
    );
    cards[0].bank_evidence_id = "foreign";
    expect(
      bankDistribution(cards).find((item) => item.key === "GREY")?.verified,
    ).toBe(false);
  });
  it("считает наличие, а не величину: ноль отличается от пропуска", () => {
    const data = response([card(0), card(1), card(2)]);
    const coverage = financialCoverage(data);
    expect(coverage[0].available).toBe(1);
    expect(coverage[0].missing).toBe(2);
    expect(coverage[0].evidence).toHaveLength(3);
    expect(data.comparison!.rows[0].comparable).toBe(false);
    data.comparison!.rows[0].cells.reverse();
    expect(financialCoverage(data)).toEqual([]);
  });
  it("не показывает непроверенную сводку и не превращает пропуски в финансовый рейтинг", () => {
    const data = response([card(0), card(1)]);
    const html = renderToStaticMarkup(
      createElement(ComparisonOverview, { data, source: () => {} }),
    );
    expect(html).toContain("Компаний в группе: 2");
    expect(html).toContain("не рейтинг надёжности");
    data.cards[0].bank_evidence_id = "foreign";
    expect(
      renderToStaticMarkup(
        createElement(ComparisonOverview, { data, source: () => {} }),
      ),
    ).toContain("Источники банковских оценок не подтверждены");
  });
});
