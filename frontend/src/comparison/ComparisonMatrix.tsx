import type { Card, Row } from "../types";
import type { SourceDetails } from "../components/EvidenceDrawer";
import { Bank, date } from "../components/Primitives";
import {
  comparisonBankKey,
  comparisonCellSources,
  displayCell,
} from "./presentation";

export function ComparisonMatrix({
  cards,
  allCards,
  rows,
  compact = false,
  title,
  shortlist,
  toggle,
  source,
  focus,
  busy,
}: {
  cards: Card[];
  allCards: Card[];
  rows: Row[];
  compact?: boolean;
  title: string;
  shortlist: string[];
  toggle: (card: Card) => void;
  source: (details: SourceDetails) => void;
  focus: (position: number) => void;
  busy: boolean;
}) {
  function bankBadge(card: Card) {
    const key = comparisonBankKey(card);
    return key === "MISSING" || key === "UNKNOWN" ? (
      <span className="bank-badge grey">
        <i />
        {key === "MISSING" ? "Сигнал не передан" : "Сигнал не распознан"}
      </span>
    ) : (
      <Bank level={key} />
    );
  }
  return (
    <div
      className={
        "table-scroll comparison-matrix" +
        (compact ? " comparison-matrix--compact" : "")
      }
      tabIndex={0}
      role="region"
      aria-label={title}
    >
      <table>
        <caption className="sr-only">{title}</caption>
        <thead>
          <tr>
            <th scope="col">
              <span className="eyebrow">
                {compact ? "Главное по компаниям" : "Показатель"}
              </span>
              <p>
                {compact
                  ? "Нажмите на значение, чтобы открыть источник"
                  : "Одинаковые строки для всех участников"}
              </p>
            </th>
            {cards.map((card) => (
              <th scope="col" key={card.snapshot_id}>
                <div className="company-column-top">
                  <span
                    className="company-number"
                    aria-label={"Компания №" + (allCards.indexOf(card) + 1)}
                  >
                    {allCards.indexOf(card) + 1}
                  </span>
                  {compact && (
                    <label className="shortlist-check">
                      <input
                        type="checkbox"
                        aria-label={"В отбор: " + card.name}
                        checked={shortlist.includes(card.snapshot_id)}
                        onChange={() => toggle(card)}
                        disabled={busy}
                      />
                      В отбор
                    </label>
                  )}
                </div>
                <button
                  className="company-link"
                  disabled={busy}
                  onClick={() => focus(allCards.indexOf(card) + 1)}
                >
                  {card.short_name || card.name}
                </button>
                <p className="comparison-inn">ИНН {card.inn}</p>
                {compact && (
                  <>
                    <button
                      className="comparison-bank-source"
                      aria-label={
                        "Банковский светофор: " + (card.short_name || card.name)
                      }
                      disabled={
                        !card.evidence.some(
                          (item) => item.evidence_id === card.bank_evidence_id,
                        )
                      }
                      onClick={() =>
                        source({
                          title: "Банковский светофор",
                          value:
                            "Внешний сигнал банка: " +
                            (card.bank_risk.raw_level ?? "не передан") +
                            ". Методика закрыта, другие строки не объясняют цвет и не гарантируют безопасность сделки.",
                          company: card.name,
                          evidence: card.evidence.filter(
                            (item) =>
                              item.evidence_id === card.bank_evidence_id,
                          ),
                        })
                      }
                    >
                      {bankBadge(card)}
                      <span aria-hidden="true">↗</span>
                    </button>
                    <p className="comparison-report-date">
                      Данные на {date(card.report_at)}
                    </p>
                  </>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} data-financial={row.key.startsWith("financial_")}>
              <th scope="row">
                {row.label}
                {row.comparison_note && (
                  <details className="row-note">
                    <summary>О показателе</summary>
                    {row.comparison_note}
                  </details>
                )}
              </th>
              {cards.map((card) => {
                const cell = row.cells.find(
                  (item) => item.snapshot_id === card.snapshot_id,
                )!;
                const evidence = comparisonCellSources(card, cell);
                const count =
                  compact &&
                  ["attention_signals", "data_gaps"].includes(row.key) &&
                  cell.value !== null &&
                  /^\d+$/.test(String(cell.value))
                    ? String(cell.value)
                    : null;
                return (
                  <td key={card.snapshot_id}>
                    <button
                      className={
                        "cell-button " +
                        (["insufficient", "conflicting", "partial"].includes(
                          cell.data_status,
                        )
                          ? "limited"
                          : "")
                      }
                      disabled={!evidence.length}
                      onClick={() =>
                        source({
                          title: row.label,
                          value: displayCell(row.key, cell),
                          company: card.name,
                          evidence,
                        })
                      }
                    >
                      {row.key === "bank_risk" ? (
                        bankBadge(card)
                      ) : (
                        <>
                          {count !== null && (
                            <span className="comparison-record-count">
                              <small>Записей:</small>
                              {count}
                            </span>
                          )}
                          <span
                            className={
                              compact && count !== null
                                ? "comparison-cell-preview"
                                : "comparison-cell-value"
                            }
                            data-negative={
                              row.key.startsWith("financial_") &&
                              /^-\d/.test(String(cell.value)) &&
                              !/^-0+(?:\.0+)?(?:[eE][+-]?\d+)?$/.test(
                                String(cell.value),
                              )
                            }
                          >
                            {displayCell(row.key, cell)}
                          </span>
                        </>
                      )}
                      <span className="source-arrow" aria-hidden="true">
                        ↗
                      </span>
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
