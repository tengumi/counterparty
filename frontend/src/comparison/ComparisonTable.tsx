import { lazy, Suspense, useId, useState } from "react";
import type { Card, ChatResponse } from "../types";
import { Action, Icon } from "../components/Primitives";
import type { SourceDetails } from "../components/EvidenceDrawer";
import {
  comparisonSections,
  filterCards,
  hasDifferences,
  summaryRowKeys,
} from "./presentation";
import { ComparisonMatrix } from "./ComparisonMatrix";

const ComparisonOverview = lazy(() =>
  import("./ComparisonOverview").then((module) => ({
    default: module.ComparisonOverview,
  })),
);
type ComparisonProps = {
  data: ChatResponse;
  shortlist: string[];
  setShortlist: (ids: string[]) => void;
  source: (details: SourceDetails) => void;
  focus: (position: number) => void;
  busy: boolean;
};

export function ComparisonTable(props: ComparisonProps) {
  // Ответ чата и фокус не сбрасывают фильтры; новый состав начинает новую сводку.
  return (
    <ComparisonContent
      key={JSON.stringify(props.data.comparison?.snapshot_ids)}
      {...props}
    />
  );
}

function ComparisonContent({
  data,
  shortlist,
  setShortlist,
  source,
  focus,
  busy,
}: ComparisonProps) {
  const id = useId();
  const [differences, setDifferences] = useState(false);
  const [onlyShortlist, setOnlyShortlist] = useState(false);
  const [bank, setBank] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const comparison = data.comparison;
  if (!comparison) return null;
  const cards = comparison.snapshot_ids.map((key) =>
    data.cards.find((card) => card.snapshot_id === key)!,
  );
  if (
    !cards.length ||
    new Set(comparison.snapshot_ids).size !== cards.length ||
    cards.some((card) => !card) ||
    comparison.rows.some(
      (row) =>
        row.cells.length !== cards.length ||
        row.cells.some(
          (cell, index) => cell.snapshot_id !== cards[index].snapshot_id,
        ),
    )
  ) {
    return (
      <p role="alert">Состав таблицы не подтверждён. Повторите сравнение.</p>
    );
  }
  const filtered = filterCards(cards, shortlist, onlyShortlist, bank, query);
  const currentPage = Math.min(
    page,
    Math.max(0, Math.ceil(filtered.length / 6) - 1),
  );
  const visible = filtered.slice(currentPage * 6, (currentPage + 1) * 6);
  // Различия проверяются во всей отфильтрованной группе, не только на странице.
  const rows = comparison.rows.filter(
    (row) => !differences || hasDifferences(row, filtered),
  );
  const summaryRows = summaryRowKeys.flatMap((key) =>
    rows.filter((row) => row.key === key),
  );
  const sections = comparisonSections(rows);
  const allKeys = [
    "overview",
    ...sections.map((section) => "section:" + section.key),
  ];
  const allOpen = allKeys.every((key) => opened.has(key));
  const toggleSection = (key: string) =>
    setOpened((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  const toggle = (card: Card) =>
    setShortlist(
      shortlist.includes(card.snapshot_id)
        ? shortlist.filter((key) => key !== card.snapshot_id)
        : [...shortlist, card.snapshot_id],
    );
  const matrixProps = {
    cards: visible,
    allCards: cards,
    shortlist,
    toggle,
    source,
    focus,
    busy,
  };
  const selectedCount = cards.filter((card) =>
    shortlist.includes(card.snapshot_id),
  ).length;
  return (
    <section
      className="comparison-area comparison-dossier"
      aria-label="Сравнение контрагентов"
    >
      <header className="comparison-heading">
        <div>
          <span className="eyebrow">Отчёт по группе</span>
          <h2>Краткое сравнение</h2>
          <p>
            Компаний: {cards.length}
            <span>·</span>В отборе: {selectedCount}
          </p>
        </div>
        <span className="period-chip">
          Финансы · {comparison.financial_year ?? "нет периода"}
        </span>
      </header>
      {data.comparison_pending && (
        <p className="notice">
          Дополнение не завершено. Новый участник ещё не включён — показана
          прежняя группа.
        </p>
      )}
      <div className="comparison-filters">
        <div className="filter-row">
          <label className="comparison-search">
            <Icon name="search" />
            <input
              aria-label="Найти в сравнении"
              placeholder="Название или ИНН"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setPage(0);
              }}
            />
          </label>
          <select
            aria-label="Банковский светофор"
            value={bank}
            onChange={(event) => {
              setBank(event.target.value);
              setPage(0);
            }}
          >
            <option value="">Все оценки банка</option>
            <option value="GREEN">Надёжный</option>
            <option value="YELLOW">Требует внимания</option>
            <option value="RED">В зоне риска</option>
            <option value="GREY">Нет оценки</option>
            <option value="MISSING">Сигнал не передан</option>
            <option value="UNKNOWN">Сигнал не распознан</option>
          </select>
        </div>
        <div className="comparison-toolbar">
          <div className="toggle-options">
            <label>
              <input
                type="checkbox"
                checked={differences}
                onChange={(event) => setDifferences(event.target.checked)}
              />
              Только различия
            </label>
            <label>
              <input
                type="checkbox"
                checked={onlyShortlist}
                onChange={(event) => {
                  setOnlyShortlist(event.target.checked);
                  setPage(0);
                }}
              />
              В отборе · {selectedCount}
            </label>
          </div>
          <span className="comparison-scroll-hint">
            Таблицу можно прокручивать ↔
          </span>
        </div>
      </div>
      {!visible.length ? (
        <div className="blank-state">
          <h3>Нет компаний по этим условиям</h3>
          <p className="muted">
            Измените фильтр или добавьте компании в отбор.
          </p>
          <button
            className="dossier-expand"
            onClick={() => {
              setQuery("");
              setBank("");
              setOnlyShortlist(false);
              setPage(0);
            }}
          >
            Сбросить фильтры
          </button>
        </div>
      ) : (
        <ComparisonMatrix
          {...matrixProps}
          rows={summaryRows}
          compact
          title="Краткое сравнение компаний"
        />
      )}
      <div className="table-footer">
        <span>
          Показано {visible.length} из {filtered.length} · Всего {cards.length}
        </span>
        {filtered.length > 6 && (
          <div className="inline-actions">
            <Action
              disabled={!currentPage}
              onClick={() => setPage(currentPage - 1)}
            >
              Назад
            </Action>
            <span>
              {currentPage + 1} / {Math.ceil(filtered.length / 6)}
            </span>
            <Action
              disabled={(currentPage + 1) * 6 >= filtered.length}
              onClick={() => setPage(currentPage + 1)}
            >
              Далее
            </Action>
          </div>
        )}
      </div>
      {visible.length > 0 && rows.length === 0 && (
        <p className="notice">
          Нет различающихся показателей для текущего фильтра. Отключите «Только
          различия», чтобы увидеть данные.
        </p>
      )}
      {visible.length > 0 && rows.length > 0 && summaryRows.length === 0 && (
        <p className="notice">
          В кратких показателях нет различий или данных. Остальные строки
          доступны в разделах ниже.
        </p>
      )}
      <p className="comparison-money-note">
        Суммы — в единицах источника: валюта и масштаб не подтверждены.
        Количество записей не является рейтингом риска и не объясняет банковский
        светофор.
      </p>
      <div className="dossier-details-heading">
        <div>
          <h3>Подробное сравнение</h3>
          <p>Все показатели и сводная статистика</p>
        </div>
        <button
          className="dossier-expand"
          aria-expanded={allOpen}
          aria-controls={id + "-details"}
          onClick={() => setOpened(allOpen ? new Set() : new Set(allKeys))}
        >
          {allOpen ? "Свернуть все" : "Раскрыть все"}
        </button>
      </div>
      <div className="dossier-sections" id={id + "-details"}>
        <details
          className="dossier-section comparison-statistics"
          open={opened.has("overview")}
        >
          <summary
            onClick={(event) => {
              event.preventDefault();
              toggleSection("overview");
            }}
          >
            <span className="dossier-section-icon">
              <Icon name="grid" />
            </span>
            <span className="dossier-section-title">
              <strong>Группа в цифрах</strong>
              <span>
                Банковские оценки и наличие финансовых данных · вся группа
              </span>
            </span>
            <span className="dossier-chevron" aria-hidden="true">
              ⌄
            </span>
          </summary>
          {opened.has("overview") && (
            <Suspense
              fallback={
                <p className="muted small" role="status">
                  Загружаем сводку…
                </p>
              }
            >
              <ComparisonOverview data={data} source={source} />
            </Suspense>
          )}
        </details>
        {!!visible.length &&
          sections.map((section) => {
            const key = "section:" + section.key;
            return (
              <details
                className="dossier-section comparison-detail-section"
                key={key}
                open={opened.has(key)}
              >
                <summary
                  onClick={(event) => {
                    event.preventDefault();
                    toggleSection(key);
                  }}
                >
                  <span className="dossier-section-icon">
                    <Icon name={section.key === "finance" ? "grid" : "file"} />
                  </span>
                  <span className="dossier-section-title">
                    <strong>{section.label}</strong>
                    <span>{section.description}</span>
                  </span>
                  <span
                    className="dossier-section-count"
                    aria-label={"Показателей: " + section.rows.length}
                  >
                    {section.rows.length}
                  </span>
                  <span className="dossier-chevron" aria-hidden="true">
                    ⌄
                  </span>
                </summary>
                <ComparisonMatrix
                  {...matrixProps}
                  rows={section.rows}
                  title={"Подробное сравнение: " + section.label}
                />
              </details>
            );
          })}
      </div>
      <p className="comparison-scope">
        Фильтры меняют только таблицы. Чат и «Группа в цифрах» учитывают всех
        участников. Номера компаний сохраняют исходный порядок.
      </p>
      <details className="limits">
        <summary>Что важно учитывать при сравнении</summary>
        <ul>
          {comparison.limitations.map((text, index) => (
            <li key={index}>{text}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
