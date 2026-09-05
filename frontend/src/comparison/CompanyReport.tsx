import { lazy, Suspense, useId, useState } from "react";
import type { Card, Finding } from "../types";
import type { SourceDetails } from "../components/EvidenceDrawer";
import { Bank, bankLabel, Icon, date } from "../components/Primitives";
import { annualPoints, exactNumber } from "./chartData";
import {
  findingPeriod,
  findingQuality,
  findingSources,
  findingTitle,
  reportOverview,
} from "./reportPresentation";

const CompanyFinancials = lazy(() =>
  import("./CompanyFinancials").then((module) => ({
    default: module.CompanyFinancials,
  })),
);
type ReportProps = { card: Card; source: (details: SourceDetails) => void };

export function CompanyReport(props: ReportProps) {
  // Другая компания всегда открывается с краткой сводки.
  return <ReportContent key={props.card.snapshot_id} {...props} />;
}

function ReportContent({ card, source }: ReportProps) {
  const id = useId();
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const overview = reportOverview(card);
  const latest = annualPoints(card).at(-1);
  const allKeys = [
    "identity",
    ...overview.sections.map((section) => "section:" + section.key),
  ];
  const allOpen = allKeys.every((key) => opened.has(key));
  const rawBank = card.bank_risk.raw_level;
  const bankKnown =
    rawBank !== null && ["GREEN", "YELLOW", "RED", "GREY"].includes(rawBank);
  const status =
    card.raw_status === "CURRENT"
      ? "Действует по данным отчёта"
      : "Статус источника: " + (card.raw_status || "не передан");
  const identityText =
    card.name + "\nИНН " + card.inn + "\nОГРН " + (card.ogrn || "не указан");
  const hasSource = (evidenceId?: string) =>
    card.evidence.some((item) => item.evidence_id === evidenceId);
  function showSource(
    evidenceId: string | undefined,
    title: string,
    value: string,
  ) {
    const evidence = card.evidence.filter(
      (item) => item.evidence_id === evidenceId,
    );
    if (evidence.length) source({ title, value, company: card.name, evidence });
  }
  function showFinding(finding: Finding) {
    const evidence = findingSources(card, finding);
    if (evidence.length)
      source({
        title: findingTitle(finding),
        value: finding.statement,
        company: card.name,
        evidence,
      });
  }
  function toggle(key: string) {
    setOpened((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }
  function preview(findings: Finding[], kind: "attention" | "limitations") {
    return (
      <section
        className={"report-brief report-brief--" + kind}
        aria-label={
          kind === "attention" ? "Сигналы внимания" : "Ограничения данных"
        }
      >
        <div className="report-brief-heading">
          <h3>
            {kind === "attention"
              ? "На что обратить внимание"
              : "Ограничения данных"}
          </h3>
          <span>{findings.length}</span>
        </div>
        {findings.slice(0, 2).map((finding) => (
          <button
            className="report-brief-fact"
            key={finding.finding_id}
            disabled={!findingSources(card, finding).length}
            onClick={() => showFinding(finding)}
          >
            <span>
              <strong>{findingTitle(finding)}</strong>
              <span className="report-brief-excerpt">{finding.statement}</span>
            </span>
            <Icon name="arrow" />
          </button>
        ))}
        {!findings.length && (
          <p className="report-brief-empty">
            {kind === "attention"
              ? "В отчёте нет записей с отметкой «требует внимания». Это не означает отсутствие рисков."
              : "Нет записей с отметкой о неполных, недостаточных или противоречивых данных. Это не гарантирует полноту отчёта."}
          </p>
        )}
        {!!findings.length && (
          <p className="report-brief-note">
            {findings.length > 2
              ? "Показаны 2 из " +
                findings.length +
                " записей. Все — в разделах ниже."
              : "Основания и полный текст — по нажатию."}
          </p>
        )}
      </section>
    );
  }
  return (
    <section className="report company-dossier" aria-label="Отчёт о компании">
      <header className="dossier-heading">
        <div className="dossier-identity">
          <span className="eyebrow">Отчёт о компании</span>
          <h2>{card.short_name || card.name}</h2>
          <button
            className="dossier-status"
            disabled={!hasSource(card.status_evidence_id)}
            onClick={() =>
              showSource(card.status_evidence_id, "Статус компании", status)
            }
          >
            <i data-current={card.raw_status === "CURRENT"} />
            {status}
          </button>
          <div className="dossier-requisites">
            <button
              disabled={!hasSource(card.identity_evidence_id)}
              onClick={() =>
                showSource(
                  card.identity_evidence_id,
                  "Реквизиты компании",
                  identityText,
                )
              }
            >
              ИНН {card.inn}
            </button>
            <span>ОГРН {card.ogrn || "не указан"}</span>
          </div>
        </div>
        <div className="dossier-bank">
          <span className="dossier-bank-label">Оценка в отчёте</span>
          <button
            disabled={!hasSource(card.bank_evidence_id)}
            onClick={() =>
              showSource(
                card.bank_evidence_id,
                "Оценка в отчёте",
                `Оценка в отчёте: ${bankLabel(rawBank)}.`,
              )
            }
          >
            {bankKnown ? (
              <Bank level={rawBank} />
            ) : (
              <span className="bank-badge grey">
                <i />
                {rawBank === null ? "Сигнал не передан" : "Сигнал не распознан"}
              </span>
            )}
            <span className="dossier-source-link">Источник и пояснение ↗</span>
          </button>
        </div>
      </header>
      <div className="dossier-summary-heading">
        <h3>Краткая сводка</h3>
        <button
          disabled={!hasSource(card.report_evidence_id)}
          onClick={() =>
            showSource(
              card.report_evidence_id,
              "Дата отчёта",
              "Данные на " + date(card.report_at),
            )
          }
        >
          Данные на {date(card.report_at)} ↗
        </button>
      </div>
      {latest ? (
        <>
          <div className="dossier-metrics">
            {(
              [
                { key: "proceeds", label: "Выручка" },
                { key: "profit", label: "Прибыль / убыток" },
              ] as const
            ).map(({ key, label }) => (
              <button
                key={key}
                onClick={() =>
                  source({
                    title: label + " · " + latest.year,
                    value:
                      exactNumber(latest.values[key]) +
                      ". Валюта и единицы измерения не подтверждены источником.",
                    company: card.name,
                    evidence: latest.evidence,
                  })
                }
              >
                <span>
                  {label}
                  <small>{latest.year}</small>
                </span>
                <strong data-negative={latest.values[key]?.startsWith("-")}>
                  {exactNumber(latest.values[key])}
                </strong>
                <span className="dossier-metric-link">Данные отчёта ↗</span>
              </button>
            ))}
          </div>
          <p className="dossier-unit-note">
            Валюта и единицы измерения не подтверждены. Динамика — в разделе
            «Финансы».
          </p>
        </>
      ) : (
        <p className="dossier-missing">
          Нет проверенных годовых данных для финансовой сводки. Доступные
          сведения — в разделах ниже.
        </p>
      )}
      <div className="dossier-brief-grid">
        {preview(overview.attention, "attention")}
        {preview(overview.limitations, "limitations")}
      </div>
      <p className="dossier-scope-note">
        Счётчики показывают записи отчёта, а не число независимых рисков.
        Подборки могут пересекаться.
      </p>
      <div className="dossier-details-heading">
        <div>
          <h3>Подробный отчёт</h3>
          <p>Раскройте нужный раздел</p>
        </div>
        <button
          className="dossier-expand"
          aria-expanded={allOpen}
          aria-controls={id + "-sections"}
          onClick={() => setOpened(allOpen ? new Set() : new Set(allKeys))}
        >
          {allOpen ? "Свернуть все" : "Раскрыть все"}
        </button>
      </div>
      <div className="dossier-sections" id={id + "-sections"}>
        <details className="dossier-section" open={opened.has("identity")}>
          <summary
            onClick={(event) => {
              event.preventDefault();
              toggle("identity");
            }}
          >
            <span className="dossier-section-icon">
              <Icon name="file" />
            </span>
            <span className="dossier-section-title">
              <strong>Реквизиты</strong>
              <span>Полное наименование, ИНН и ОГРН</span>
            </span>
            <span className="dossier-chevron" aria-hidden="true">
              ⌄
            </span>
          </summary>
          <div className="dossier-section-body">
            <dl className="dossier-identity-list">
              <dt>Полное наименование</dt>
              <dd>{card.name}</dd>
              <dt>ИНН</dt>
              <dd>{card.inn}</dd>
              <dt>ОГРН</dt>
              <dd>{card.ogrn || "Не указан"}</dd>
            </dl>
            <button
              className="text-button"
              disabled={!hasSource(card.identity_evidence_id)}
              onClick={() =>
                showSource(
                  card.identity_evidence_id,
                  "Реквизиты компании",
                  identityText,
                )
              }
            >
              Источник реквизитов ↗
            </button>
          </div>
        </details>
        {overview.sections.map((section) => {
          const key = "section:" + section.key;
          return (
            <details
              className="dossier-section"
              key={key}
              open={opened.has(key)}
            >
              <summary
                onClick={(event) => {
                  event.preventDefault();
                  toggle(key);
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
                  aria-label={"Записей: " + section.findings.length}
                >
                  {section.findings.length}
                </span>
                <span className="dossier-chevron" aria-hidden="true">
                  ⌄
                </span>
              </summary>
              <div className="dossier-section-body">
                {section.key === "finance" && opened.has(key) && (
                  <Suspense
                    fallback={
                      <p className="muted small" role="status">
                        Загружаем финансовые показатели…
                      </p>
                    }
                  >
                    <CompanyFinancials card={card} source={source} />
                  </Suspense>
                )}
                <div className="dossier-findings">
                  {section.findings.map((finding) => (
                    <article
                      className="dossier-finding"
                      key={finding.finding_id}
                    >
                      <span
                        className="dossier-finding-marker"
                        data-attention={finding.severity === "attention"}
                        aria-label={
                          finding.severity === "attention"
                            ? "Требует внимания"
                            : "Сведение"
                        }
                      >
                        {finding.severity === "attention" ? "!" : "·"}
                      </span>
                      <div>
                        <div className="dossier-finding-meta">
                          {findingPeriod(finding.period) && (
                            <span>{findingPeriod(finding.period)}</span>
                          )}
                          {findingQuality(finding.data_status) && (
                            <span>{findingQuality(finding.data_status)}</span>
                          )}
                        </div>
                        <p>{finding.statement}</p>
                        <button
                          className="text-button"
                          disabled={!findingSources(card, finding).length}
                          onClick={() => showFinding(finding)}
                        >
                          Источник и дата ↗
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}
