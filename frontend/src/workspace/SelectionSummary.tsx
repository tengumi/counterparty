import type { Card } from "../types";
import { Bank, bankLabel, date } from "../components/Primitives";
import type { SourceDetails } from "../components/EvidenceDrawer";

export function SelectionSummary({
  cards,
  focused,
  busy,
  source,
  focus,
}: {
  cards: Card[];
  focused: string | null;
  busy: boolean;
  source: (details: SourceDetails) => void;
  focus: (position: number) => void;
}) {
  return (
    <aside className="selection-summary" aria-label="Выбранные компании">
      <div className="selection-heading">
        <h2>{cards.length > 1 ? "Участники сравнения" : "Компания"}</h2>
        <span>{cards.length}</span>
      </div>
      <div className="selection-companies">
        {cards.map((card, i) => {
          const bankEvidence = card.evidence.filter(
            (e) => e.evidence_id === card.bank_evidence_id,
          );
          const raw = card.bank_risk.raw_level;
          const known =
            raw !== null && ["GREEN", "YELLOW", "RED", "GREY"].includes(raw);
          return (
            <article
              className="selection-company"
              data-focused={focused === card.snapshot_id}
              key={card.snapshot_id}
            >
              <div className="selection-identity">
                {cards.length > 1 && (
                  <span className="company-position">{i + 1}</span>
                )}
                {cards.length > 1 ? (
                  <button
                    className="company-name"
                    disabled={busy}
                    aria-pressed={focused === card.snapshot_id}
                    onClick={() => focus(i + 1)}
                  >
                    {card.short_name || card.name}
                  </button>
                ) : (
                  <h3>{card.short_name || card.name}</h3>
                )}
              </div>
              <p>ИНН {card.inn}</p>
              <p className="selection-date">Отчёт от {date(card.report_at)}</p>
              <button
                className="selection-risk"
                disabled={!bankEvidence.length}
                onClick={() =>
                  source({
                    title: "Оценка в отчёте",
                    company: card.name,
                    value: `Оценка в отчёте: ${bankLabel(raw)}.`,
                    evidence: bankEvidence,
                  })
                }
              >
                <span className="selection-risk-label">Оценка в отчёте</span>
                {known ? (
                  <Bank level={raw} />
                ) : (
                  <span className="bank-badge grey">
                    <i />
                    {raw === null ? "Не передана" : "Не распознана"}
                  </span>
                )}
              </button>
            </article>
          );
        })}
      </div>
      {cards.length > 1 && (
        <p className="selection-hint">
          Нажмите на компанию, чтобы обсудить её отдельно.
        </p>
      )}
    </aside>
  );
}
