import type { ChatResponse, Evidence } from "../types";

export function responseSources(result: ChatResponse): Evidence[] {
  const cards = result.comparison
    ? result.comparison.snapshot_ids.map((id) =>
        result.cards.find((c) => c.snapshot_id === id),
      )
    : result.card
      ? [result.card]
      : [];
  const ledger = new Map<string, Evidence>();
  const owners = new Map<string, string>();
  cards.forEach((card, index) => {
    if (!card) throw new Error("Состав ответа не подтверждён.");
    for (const item of card.evidence) {
      if (
        owners.has(item.evidence_id) &&
        owners.get(item.evidence_id) !== card.snapshot_id
      )
        throw new Error("Источник ответа неоднозначно связан с компанией.");
      ledger.set(item.evidence_id, {
        ...item,
        company_name: `${result.comparison ? `Компания №${index + 1} · ` : ""}${card.short_name || card.name}`,
      });
      owners.set(item.evidence_id, card.snapshot_id);
    }
  });
  const ids = [...new Set(result.answer_claims.flatMap((c) => c.evidence_ids))];
  if (ids.some((id) => !ledger.has(id)))
    throw new Error(
      "Не удалось подтвердить источники ответа. Повторите запрос.",
    );
  return ids.map((id) => ledger.get(id)!);
}
