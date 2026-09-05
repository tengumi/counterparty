import type { Card, Cell, Row } from "../types";
import { bankLabel } from "../components/Primitives";

export const summaryRowKeys = [
  "company_status",
  "financial_proceeds",
  "financial_profit",
  "attention_signals",
  "data_gaps",
];

export function comparisonSections(rows: Row[]) {
  const labels: Record<string, [string, string]> = {
    company: ["Компания и реквизиты", "Тип, статус и даты отчётов"],
    bank: ["Оценка в отчёте", "Уровни оценки выбранных компаний"],
    finance: ["Финансы", "Все показатели за период сравнения"],
    arbitration: ["Судебные дела", "Роли компаний и статус разбирательств"],
    enforcement: [
      "Исполнительные производства",
      "Количество, активность и известные суммы",
    ],
    signals: [
      "Сигналы и ограничения",
      "Полный текст записей для внимания и пробелов в данных",
    ],
  };
  const grouped = new Map<string, Row[]>();
  for (const row of rows) {
    const key = ["attention_signals", "data_gaps"].includes(row.key)
      ? "signals"
      : row.key === "bank_risk"
        ? "bank"
        : row.category === "financial"
          ? "finance"
          : row.category;
    grouped.set(key, [...(grouped.get(key) ?? []), row]);
  }
  const order = Object.keys(labels);
  return [
    ...order.filter((key) => grouped.has(key)),
    ...[...grouped.keys()].filter((key) => !order.includes(key)),
  ].map((key) => ({
    key,
    label: labels[key]?.[0] ?? "Другие сведения",
    description: labels[key]?.[1] ?? "Дополнительные показатели отчётов",
    rows: grouped.get(key)!,
  }));
}

export function comparisonCellSources(card: Card, cell: Cell) {
  if (cell.snapshot_id !== card.snapshot_id) return [];
  const sources = cell.evidence_ids.map((id) =>
    card.evidence.find((item) => item.evidence_id === id),
  );
  return sources.length && sources.every((item) => item !== undefined)
    ? sources
    : [];
}

export function comparisonBankKey(card: Card) {
  const raw = card.bank_risk.raw_level;
  return raw === null
    ? "MISSING"
    : ["GREEN", "YELLOW", "RED", "GREY"].includes(raw)
      ? raw
      : "UNKNOWN";
}

// Меняем только представление: денежные значения не преобразуем в Number.
export function displayCell(key: string, cell: Cell): string {
  if (key === "bank_risk")
    return bankLabel(cell.value === null ? null : String(cell.value));
  const text = cell.display_value;
  if (key === "report_date" && /^\d{4}-\d{2}-\d{2}T/.test(text))
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow",
    }).format(new Date(text));
  if (key === "company_status")
    return (
      (
        { CURRENT: "Действует", LIQUIDATED: "Ликвидирована" } as Record<
          string,
          string
        >
      )[text] || text
    );
  if (key.startsWith("financial_") && /^-?\d+(?:\.\d+)?$/.test(text)) {
    const [whole, fraction] = text.split(".");
    return (
      whole.replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f") +
      (fraction ? `,${fraction}` : "")
    );
  }
  return text.replaceAll("с приоритетом attention", "требующих внимания");
}

export function filterCards(
  cards: Card[],
  shortlist: string[],
  onlyShortlist: boolean,
  bank: string,
  query: string,
): Card[] {
  return cards.filter(
    (c) =>
      (!onlyShortlist || shortlist.includes(c.snapshot_id)) &&
      (!bank || comparisonBankKey(c) === bank) &&
      `${c.name} ${c.short_name || ""} ${c.inn}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
}

export function hasDifferences(row: Row, cards: Card[]): boolean {
  const selected = new Map(cards.map((c) => [c.snapshot_id, c]));
  return (
    new Set(
      row.cells
        .filter((c) => selected.has(c.snapshot_id))
        .map(
          (c) =>
            `${c.display_value}:${c.data_status}:${row.key === "bank_risk" ? comparisonBankKey(selected.get(c.snapshot_id)!) : ""}`,
        ),
    ).size > 1
  );
}
