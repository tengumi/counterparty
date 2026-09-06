import type { Card, Finding } from "../types";

const sectionLabels: Record<string, [string, string]> = {
  company: [
    "Компания и лицензии",
    "Статус, регистрационные сведения и разрешения",
  ],
  finance: ["Финансы", "Показатели по годам, графики и структура баланса"],
  arbitration: ["Судебные дела", "Арбитраж и роли компании в разбирательствах"],
  enforcement: [
    "Исполнительные производства",
    "Количество, активность и указанные суммы",
  ],
  reputation: [
    "Сигналы поставщика",
    "Положительные и отрицательные сведения отчёта",
  ],
  data_quality: [
    "Полнота и ограничения",
    "Даты, пропуски и сопоставимость данных",
  ],
  licenses: ["Лицензии", "Разрешения, представленные в источнике"],
};

export function reportOverview(card: Card) {
  const grouped = new Map<string, Finding[]>();
  for (const finding of card.findings) {
    const key = finding.category === "financial" ? "finance" : finding.category;
    grouped.set(key, [...(grouped.get(key) ?? []), finding]);
  }
  const order = Object.keys(sectionLabels);
  const keys = [
    ...order.filter((key) => grouped.has(key)),
    ...[...grouped.keys()].filter((key) => !order.includes(key)),
  ];
  return {
    sections: keys.map((key) => ({
      key,
      label: sectionLabels[key]?.[0] ?? "Другие сведения",
      description: sectionLabels[key]?.[1] ?? "Дополнительные факты из отчёта",
      findings: grouped.get(key)!,
    })),
    // Это записи отчёта, не независимые риски. Две подборки могут пересекаться.
    attention: card.findings.filter(
      (finding) => finding.severity === "attention",
    ),
    limitations: card.findings.filter((finding) =>
      ["partial", "conflicting", "insufficient"].includes(finding.data_status),
    ),
  };
}

export function findingSources(card: Card, finding: Finding) {
  const sources = finding.evidence_ids.map((id) =>
    card.evidence.find((item) => item.evidence_id === id),
  );
  // Не выдаём неполный набор оснований или источник из другой карточки.
  return sources.length && sources.every((item) => item !== undefined)
    ? sources
    : [];
}

export function findingTitle(finding: Finding) {
  const labels: Record<string, string> = {
    money_units_confirmed: "Валюта и единицы измерения",
    financial_loss: "Отрицательная прибыль",
    negative_equity: "Отрицательный капитал и резервы",
    financial_fields_missing: "Не все финансовые показатели заполнены",
    financial_period: "Финансовые показатели",
    financial_period_gap: "Пропущенные годы отчётности",
    reputation_summary: "Сигналы в отчёте поставщика",
    provider_negative_signal: "Отрицательный сигнал поставщика",
    report_stale: "Давность отчёта",
  };
  const period = findingPeriod(finding.period);
  return `${labels[finding.code ?? ""] ?? "Факт из отчёта"}${period ? ` · ${period}` : ""}`;
}

export function findingPeriod(period: Finding["period"]) {
  // В period бывают не только годы, но и внутренние коды сигналов.
  const value = String(period ?? "");
  if (/^(19|20|21|22)\d{2}$/.test(value)) return `${value} год`;
  if (/^(19|20|21|22)\d{2}:(19|20|21|22)\d{2}$/.test(value))
    return value.replace(":", "–");
  return "";
}

export function findingQuality(status: string) {
  return (
    {
      partial: "Данные неполные",
      insufficient: "Недостаточно данных",
      conflicting: "Есть противоречия",
      inapplicable: "Неприменимо",
    } as Record<string, string>
  )[status];
}
