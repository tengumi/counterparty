import { describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Card, Finding } from "../types";
import { CompanyReport } from "./CompanyReport";
import {
  findingPeriod,
  findingSources,
  findingTitle,
  reportOverview,
} from "./reportPresentation";

// В Node проверяем нашу разметку, внешнюю библиотеку — в браузере.
vi.mock("@alfalab/core-components-button", () => ({
  Button: ({ children, ...props }: { children: import("react").ReactNode }) =>
    createElement("button", props, children),
}));

const finding = (
  id: string,
  category = "finance",
  status = "confirmed",
  severity = "info",
): Finding => ({
  finding_id: id,
  category,
  data_status: status,
  severity,
  statement: "Полный проверенный текст " + id,
  evidence_ids: [id],
});
function card(findings: Finding[] = []): Card {
  return {
    snapshot_id: "s",
    name: "Полное наименование",
    short_name: "Краткое имя",
    inn: "",
    ogrn: "",
    report_at: "2026-09-01",
    raw_status: "CURRENT",
    party_type: "LEGAL",
    bank_risk: { raw_level: "YELLOW", display_level: "GREEN" },
    findings,
    evidence: findings.map((item) => ({
      evidence_id: item.finding_id,
      source_name: "Проверочный источник",
      report_at: "2026-09-01",
      quality: "confirmed",
      coverage: "present",
      canonical_path: "analysis.fact",
    })),
  };
}
const html = (value: Card) =>
  renderToStaticMarkup(
    createElement(CompanyReport, { card: value, source: () => {} }),
  );

describe("Краткий и подробный отчёт", () => {
  it("сохраняет каждую запись, включая новые категории и финансовый alias", () => {
    const input = [
      finding("a", "custom"),
      finding("b", "financial"),
      finding("c", "finance"),
      finding("d", "company"),
    ];
    const overview = reportOverview(card(input));
    expect(
      overview.sections
        .flatMap((section) => section.findings.map((item) => item.finding_id))
        .sort(),
    ).toEqual(["a", "b", "c", "d"]);
    expect(
      overview.sections.find((section) => section.key === "finance")?.findings,
    ).toHaveLength(2);
    expect(overview.sections.at(-1)?.label).toBe("Другие сведения");
  });
  it("считает записи, допускает пересечение и не считает подтверждённый возраст отчёта пробелом", () => {
    const overlap = finding("a", "finance", "partial", "attention");
    const overview = reportOverview(
      card([
        overlap,
        finding("b", "data_quality"),
        finding("c", "company", "inapplicable"),
        finding("d", "arbitration", "insufficient"),
        finding("e", "finance", "conflicting"),
      ]),
    );
    expect(overview.attention).toEqual([overlap]);
    expect(overview.limitations.map((item) => item.finding_id)).toEqual([
      "a",
      "d",
      "e",
    ]);
  });
  it("возвращает все основания только из текущей карточки", () => {
    const value = card([finding("a"), finding("b")]);
    const item = { ...finding("a"), evidence_ids: ["a", "b"] };
    expect(findingSources(value, item)).toEqual(value.evidence);
    expect(
      findingSources(value, { ...item, evidence_ids: ["a", "foreign"] }),
    ).toEqual([]);
    expect(findingSources(value, { ...item, evidence_ids: [] })).toEqual([]);
  });
  it("изначально сворачивает разделы, но сохраняет полный текст и кнопку каждого источника", () => {
    const input = Array.from({ length: 4 }, (_, i) =>
      finding("a" + i, "finance", "confirmed", "attention"),
    );
    const markup = html(card(input));
    expect(markup).toContain("Краткое имя</h2>");
    expect(markup).toContain("Раскрыть все");
    expect(markup.match(/<details/g)).toHaveLength(2);
    expect(markup).not.toMatch(/<details[^>]*\sopen/);
    expect(markup).not.toContain("Финансовые показатели компании");
    for (const item of input) expect(markup).toContain(item.statement);
    expect(markup.match(/Источник и дата ↗/g)).toHaveLength(4);
    expect(markup).toContain("Показаны 2 из 4 записей");
  });
  it("берёт неизменённый raw светофор, отличает отсутствие, неизвестное значение и серый", () => {
    const value = card();
    expect(html(value)).toContain("Требует внимания");
    for (const [raw, label] of [
      [null, "Сигнал не передан"],
      ["NEW_VALUE", "Сигнал не распознан"],
      ["GREY", "Нет оценки"],
    ] as const) {
      value.bank_risk.raw_level = raw;
      expect(html(value)).toContain(label);
      expect(value.bank_risk.display_level).toBe("GREEN");
    }
  });
  it("не заменяет пропуски нулями и не назначает валюту", () => {
    const item = { ...finding("year"), code: "financial_period", period: 2025 };
    const value = card([item]);
    value.evidence[0].canonical_path = "analysis.financial_period";
    value.evidence[0].value = {
      year: 2025,
      proceeds: "0",
      profit: null,
      assets_total: "18014398509481985.03",
      equity: null,
    };
    const markup = html(value);
    expect(markup).toMatch(/<strong[^>]*>0<\/strong>/);
    expect(markup).toMatch(/<strong[^>]*>Нет данных<\/strong>/);
    expect(markup).toContain("Валюта и единицы измерения не подтверждены");
    expect(markup).not.toContain("₽");
  });
  it("не выводит коды сигналов как годы", () => {
    expect(findingPeriod(2025)).toBe("2025 год");
    expect(findingPeriod("2023:2024")).toBe("2023–2024");
    expect(findingPeriod("massAddress")).toBe("");
    expect(
      findingTitle({
        ...finding("a"),
        code: "provider_negative_signal",
        period: "fnsBlocking",
      }),
    ).toBe("Отрицательный сигнал поставщика");
  });
  it("показывает неизвестный статус без вывода о деятельности компании", () => {
    const value = card();
    value.raw_status = "UNRECOGNIZED";
    expect(html(value)).toContain("Статус источника: UNRECOGNIZED");
    expect(html(value)).not.toContain("Действует по данным отчёта");
  });
});
