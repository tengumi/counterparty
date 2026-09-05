import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import {
  comparisonBankKey,
  comparisonCellSources,
  comparisonSections,
  displayCell,
  filterCards,
  hasDifferences,
} from "../comparison/presentation";
import { ComparisonTable } from "../comparison/ComparisonTable";
import { responseSources } from "./evidence";
import { scrollConversation } from "../components/ChatPanel";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { bankLabel } from "../components/Primitives";
import type { Card, Cell, ChatResponse, Row } from "../types";
import { api } from "../api";
import { restoredWorkspaceView } from "./useWorkspace";

// В Node проверяем нашу таблицу; CSS внешней библиотеки проверяется браузером.
vi.mock("@alfalab/core-components-button", () => ({
  Button: ({ children, ...props }: { children: import("react").ReactNode }) =>
    createElement("button", props, children),
}));

const card = (i: number): Card => ({
  snapshot_id: `s${i}`,
  name: `Компания ${i}`,
  short_name: `К${i}`,
  inn: `77${i}`,
  ogrn: "",
  report_at: "2026-09-01T00:00:00Z",
  raw_status: "CURRENT",
  party_type: "LEGAL",
  bank_risk: {
    display_level: i % 2 ? "RED" : "GREEN",
    raw_level: i % 2 ? "RED" : "GREEN",
  },
  findings: [],
  evidence: [
    {
      evidence_id: `e${i}`,
      source_name: "Источник",
      report_at: "2026-09-01",
      quality: "confirmed",
      coverage: "provided",
      canonical_path: "status",
    },
  ],
});
const cell = (i: number, text = "0", status = "confirmed"): Cell => ({
  snapshot_id: `s${i}`,
  display_value: text,
  value: text,
  data_status: status,
  evidence_ids: [`e${i}`],
});
const row = (cells: Cell[]): Row => ({
  key: "financial_profit",
  label: "Прибыль",
  category: "finance",
  comparable: true,
  comparison_note: "",
  cells,
});
function response(n = 3): ChatResponse {
  const cards = Array.from({ length: n }, (_, i) => card(i));
  return {
    session_id: "s",
    answer: "Ответ",
    status: "compared",
    llm_used: false,
    cards,
    card: null,
    candidates: [],
    comparison_selections: [],
    comparison_pending: false,
    focus_snapshot_id: null,
    comparison: {
      snapshot_ids: cards.map((c) => c.snapshot_id),
      rows: [row(cards.map((_, i) => cell(i)))],
      financial_year: 2025,
      limitations: [],
    },
    answer_claims: [{ text: "Ответ", evidence_ids: ["e0", `e${n - 1}`] }],
  };
}
describe("Представление без пересчёта фактов", () => {
  it("восстанавливает выбранный проектный диалог после обновления страницы", () => {
    expect(restoredWorkspaceView("project")).toBe("project");
    expect(restoredWorkspaceView("comparison")).toBe("comparison");
    expect(restoredWorkspaceView(null)).toBe("project");
    expect(restoredWorkspaceView("unknown")).toBe("project");
  });
  it("ошибки валидации и сети показываются понятным текстом без внутренних структур", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    try {
      fetch.mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            detail: [{ loc: ["body", "question"], msg: "Field required" }],
          }),
          { status: 422 },
        ),
      );
      await expect(api("/api/chat")).rejects.toThrow(
        "Проверьте введённые данные",
      );
      fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
      await expect(api("/api/chat")).rejects.toThrow("Нет связи с приложением");
      fetch.mockResolvedValueOnce(
        new Response(
          JSON.stringify({ detail: "Сначала завершите выбор компаний." }),
          { status: 409 },
        ),
      );
      await expect(api("/api/chat")).rejects.toThrow(
        "Сначала завершите выбор компаний",
      );
      fetch.mockResolvedValueOnce(new Response("не JSON", { status: 200 }));
      await expect(api("/api/chat")).rejects.toThrow("Получен неполный ответ");
    } finally {
      fetch.mockRestore();
    }
  });
  it("принимает условия пользователя как отдельный источник, без замены фактов отчёта", () => {
    const data = response();
    data.evidence = [
      {
        evidence_id: "deal:advance",
        source_name: "Сообщено пользователем",
        report_at: "2026-09-01",
        quality: "user_context",
        coverage: "provided",
        canonical_path: "deal.advance",
        value: "50%",
      },
    ];
    data.answer_claims = [
      { text: "Вы указали аванс 50%", evidence_ids: ["deal:advance"] },
    ];
    expect(responseSources(data)[0].quality).toBe("user_context");
    data.evidence[0].evidence_id = "e0";
    expect(() => responseSources(data)).toThrow("не может заменять");
  });
  it("новый ответ прокручивает только сообщения, а не страницу отчёта", () => {
    const container = {
      scrollTop: 0,
      scrollHeight: 900,
      scrollIntoView: vi.fn(),
    };
    scrollConversation(container);
    expect(container.scrollTop).toBe(900);
    expect(container.scrollIntoView).not.toHaveBeenCalled();
    expect(() => scrollConversation(null)).not.toThrow();
  });
  it("сохраняет точность денег за пределами Number", () => {
    expect(
      displayCell("financial_profit", cell(0, "18014398509481985.03")),
    ).toBe("18\u202f014\u202f398\u202f509\u202f481\u202f985,03");
    expect(displayCell("financial_profit", cell(0, "Нет данных"))).toBe(
      "Нет данных",
    );
  });
  it.each([
    ["GREEN", "Надёжный"],
    ["YELLOW", "Требует внимания"],
    ["RED", "В зоне риска"],
    ["GREY", "Нет оценки"],
    [null, "Сигнал не передан"],
    ["NEW_CODE", "Сигнал не распознан"],
    ["__proto__", "Сигнал не распознан"],
  ])("подписи оценки %s русифицируются без изменения источника", (raw, label) => {
    const sourceCell = Object.freeze({
      ...cell(0),
      value: raw,
      display_value: `${raw} — исходная подпись поставщика`,
    });
    expect(bankLabel(raw)).toBe(label);
    expect(displayCell("bank_risk", sourceCell)).toBe(label);
    expect(sourceCell.value).toBe(raw);
    expect(sourceCell.display_value).toBe(
      `${raw} — исходная подпись поставщика`,
    );
  });
  it("совмещает поиск, банковский фильтр и ручной отбор без нового ранжирования", () => {
    expect(
      filterCards(
        [card(0), card(1), card(2)],
        ["s0", "s2"],
        true,
        "GREEN",
        "К2",
      ).map((c) => c.snapshot_id),
    ).toEqual(["s2"]);
  });
  it("различает отсутствие и ноль, сравнивает весь отфильтрованный состав", () => {
    expect(
      hasDifferences(row([cell(0), cell(1, "Нет данных", "insufficient")]), [
        card(0),
        card(1),
      ]),
    ).toBe(true);
    expect(
      hasDifferences(row([cell(0), cell(1, "Нет данных")]), [card(0)]),
    ).toBe(false);
  });
  it("показывает страницу, но не обрезает группу из 100 компаний", () => {
    const html = renderToStaticMarkup(
      createElement(ComparisonTable, {
        data: response(100),
        shortlist: [],
        setShortlist: () => {},
        source: () => {},
        focus: () => {},
        busy: false,
      }),
    );
    expect(html).toContain("Всего 100");
    expect(html).toContain("1 / 17");
    expect(html).not.toContain("К99</button>");
  });
  it("не отображает матрицу с подменённым порядком", () => {
    const data = response();
    data.comparison!.rows[0].cells.reverse();
    expect(
      renderToStaticMarkup(
        createElement(ComparisonTable, {
          data,
          shortlist: [],
          setShortlist: () => {},
          source: () => {},
          focus: () => {},
          busy: false,
        }),
      ),
    ).toContain("Состав таблицы не подтверждён");
  });
  it("в подробных разделах сохраняет все строки, включая незнакомую категорию", () => {
    const input = [
      row([cell(0)]),
      {
        ...row([cell(0)]),
        key: "financial_assets_total",
        category: "financial",
      },
      { ...row([cell(0)]), key: "data_gaps", category: "data_quality" },
      { ...row([cell(0)]), key: "new_metric", category: "custom" },
      { ...row([cell(0)]), key: "bank_risk", category: "company" },
    ];
    const sections = comparisonSections(input);
    expect(
      sections
        .flatMap((section) => section.rows.map((item) => item.key))
        .sort(),
    ).toEqual(input.map((item) => item.key).sort());
    expect(
      sections.find((section) => section.key === "finance")?.rows,
    ).toHaveLength(2);
    expect(
      sections.find((section) => section.key === "signals")?.rows[0].key,
    ).toBe("data_gaps");
    expect(sections.at(-1)?.label).toBe("Другие сведения");
  });
  it("не теряет различие на следующей странице группы", () => {
    const cards = Array.from({ length: 7 }, (_, i) => card(i));
    const values = cards.map((_, i) => cell(i, i === 6 ? "1" : "0"));
    expect(hasDifferences(row(values), cards)).toBe(true);
    expect(hasDifferences(row(values), cards.slice(0, 6))).toBe(false);
    expect(filterCards(cards, [], false, "", "К6")[0].snapshot_id).toBe("s6");
  });
  it("не смешивает серый, отсутствующий и неизвестный банковский сигнал", () => {
    const cards = [card(0), card(1), card(2)];
    cards[0].bank_risk = { display_level: "GREY", raw_level: "GREY" };
    cards[1].bank_risk = { display_level: "GREY", raw_level: null };
    cards[2].bank_risk = { display_level: "GREY", raw_level: "NEW_CODE" };
    expect(cards.map(comparisonBankKey)).toEqual([
      "GREY",
      "MISSING",
      "UNKNOWN",
    ]);
    expect(filterCards(cards, [], false, "GREY", "")).toEqual([cards[0]]);
    expect(filterCards(cards, [], false, "MISSING", "")).toEqual([cards[1]]);
    expect(filterCards(cards, [], false, "UNKNOWN", "")).toEqual([cards[2]]);
    const bankRow = {
      ...row(cards.map((_, i) => cell(i, "Нет оценки"))),
      key: "bank_risk",
    };
    expect(hasDifferences(bankRow, cards.slice(1))).toBe(true);
  });
  it("не открывает неполные основания или ячейку другой компании", () => {
    const company = card(0);
    expect(comparisonCellSources(company, cell(0))).toEqual(company.evidence);
    expect(
      comparisonCellSources(company, {
        ...cell(0),
        evidence_ids: ["e0", "foreign"],
      }),
    ).toEqual([]);
    expect(
      comparisonCellSources(company, { ...cell(1), evidence_ids: ["e0"] }),
    ).toEqual([]);
    expect(
      comparisonCellSources(company, { ...cell(0), evidence_ids: [] }),
    ).toEqual([]);
  });
  it("показывает краткую матрицу и по умолчанию закрывает графики и подробности", () => {
    const data = response();
    data.comparison!.financial_year = 2024;
    data.comparison!.rows = [
      row([
        cell(0, "0"),
        cell(1, "Нет данных", "insufficient"),
        cell(2, "18014398509481985.03"),
      ]),
      {
        ...row([cell(0), cell(1), cell(2)]),
        key: "legal_fact",
        label: "Полный юридический факт",
        category: "custom",
        comparison_note: "Оговорка из матрицы",
      },
    ];
    const html = renderToStaticMarkup(
      createElement(ComparisonTable, {
        data,
        shortlist: [],
        setShortlist: () => {},
        source: () => {},
        focus: () => {},
        busy: false,
      }),
    );
    expect(html).toContain("Краткое сравнение компаний");
    expect(html).toContain("Финансы · 2024");
    expect(html).toContain(
      "18\u202f014\u202f398\u202f509\u202f481\u202f985,03",
    );
    expect(html).toContain("Нет данных");
    expect(html).toContain(">0</span>");
    expect(html).toContain("Полный юридический факт");
    expect(html).toContain("Оговорка из матрицы");
    expect(html).not.toMatch(/<details[^>]*\sopen/);
    expect(html).not.toContain("recharts");
    expect(html).not.toContain("₽");
  });
  it("отклоняет дубли и недостающих участников", () => {
    for (const change of [
      (data: ChatResponse) => {
        data.comparison!.snapshot_ids[1] = "s0";
      },
      (data: ChatResponse) => {
        data.cards.pop();
      },
    ]) {
      const data = response();
      change(data);
      const html = renderToStaticMarkup(
        createElement(ComparisonTable, {
          data,
          shortlist: [],
          setShortlist: () => {},
          source: () => {},
          focus: () => {},
          busy: false,
        }),
      );
      expect(html).toContain("Состав таблицы не подтверждён");
      expect(html).not.toContain("<table");
    }
  });
});
describe("Источники ответа", () => {
  it("наличие основания не выдаётся за наличие каждого показателя внутри него", () => {
    const html = renderToStaticMarkup(
      createElement(EvidenceDrawer, {
        close: () => {},
        details: {
          title: "Прибыль",
          value: "Нет данных",
          evidence: [
            { ...card(0).evidence[0], coverage: "present", quality: "partial" },
          ],
        },
      }),
    );
    expect(html).toContain("Основание присутствует в отчёте");
    expect(html).not.toContain("Показатель присутствует в отчёте");
  });
  it("сохраняет владельца группового источника даже при фокусе", () => {
    const data = response();
    data.card = data.cards[0];
    data.focus_snapshot_id = "s0";
    expect(responseSources(data).map((e) => e.company_name)).toEqual([
      "Компания №1 · К0",
      "Компания №3 · К2",
    ]);
  });
  it("отклоняет чужой и неоднозначный источник", () => {
    const data = response();
    data.answer_claims[0].evidence_ids.push("foreign");
    expect(() => responseSources(data)).toThrow();
    data.answer_claims[0].evidence_ids.pop();
    data.cards[1].evidence = data.cards[0].evidence;
    expect(() => responseSources(data)).toThrow();
  });
});
