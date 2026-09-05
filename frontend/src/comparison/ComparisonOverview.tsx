import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { ChatResponse } from "../types";
import type { SourceDetails } from "../components/EvidenceDrawer";
import { bankDistribution, financialCoverage } from "./chartData";

export function ComparisonOverview({
  data,
  source,
}: {
  data: ChatResponse;
  source: (details: SourceDetails) => void;
}) {
  const comparison = data.comparison;
  if (!comparison || !comparison.snapshot_ids.length) return null;
  const cards = comparison.snapshot_ids.map((id) =>
    data.cards.find((card) => card.snapshot_id === id),
  );
  if (
    cards.some((card) => !card) ||
    new Set(comparison.snapshot_ids).size !== cards.length
  )
    return null;
  const segments = bankDistribution(cards.filter((card) => card !== undefined));
  const coverage = financialCoverage(data);
  const total = cards.length;
  return (
    <section className="comparison-overview" aria-label="Сводка по всей группе">
      <div className="visual-heading">
        <div>
          <h2>Группа в цифрах</h2>
          <p className="muted small">
            Компаний в группе: {total} · фильтры таблицы не меняют сводку
          </p>
        </div>
        <span className="period-chip">
          {comparison.financial_year
            ? `Финансы · ${comparison.financial_year}`
            : "Нет финансового периода"}
        </span>
      </div>
      <div className="overview-grid">
        <article className="overview-panel">
          <h3>Банковский светофор</h3>
          {segments.every((segment) => segment.verified) ? (
            <>
              <div className="bank-chart-layout">
                <div className="donut-wrap">
                  <ResponsiveContainer width="100%" height={180} minWidth={0}>
                    <PieChart accessibilityLayer>
                      <Pie
                        data={segments.filter((segment) => segment.count > 0)}
                        dataKey="count"
                        nameKey="label"
                        innerRadius={58}
                        outerRadius={77}
                        paddingAngle={2}
                        stroke="none"
                        isAnimationActive={false}
                      >
                        {segments
                          .filter((segment) => segment.count > 0)
                          .map((segment) => (
                            <Cell key={segment.key} fill={segment.color} />
                          ))}
                      </Pie>
                      <Tooltip
                        content={({ active, payload }) =>
                          active && payload?.length ? (
                            <div className="chart-tooltip">
                              <span>{String(payload[0].name)}</span>
                              <strong>
                                {String(payload[0].value)} из {total}
                              </strong>
                            </div>
                          ) : null
                        }
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="donut-label" aria-hidden="true">
                    <strong>{total}</strong>
                    <span>в группе</span>
                  </div>
                </div>
                <div className="bank-legend">
                  {segments
                    .filter(
                      (segment) =>
                        segment.count > 0 ||
                        ["GREEN", "YELLOW", "RED", "GREY"].includes(
                          segment.key,
                        ),
                    )
                    .map((segment) => (
                      <button
                        key={segment.key}
                        onClick={() =>
                          source({
                            title: `Банковский светофор · ${segment.label}`,
                            value: `${segment.count} из ${total} компаний. Ниже — данные отчётов, использованные в сводке.`,
                            evidence: segment.evidence,
                          })
                        }
                      >
                        <i
                          style={{ background: segment.color }}
                          aria-hidden="true"
                        />
                        <span>{segment.label}</span>
                        <strong>{segment.count}</strong>
                      </button>
                    ))}
                </div>
              </div>
              <p className="chart-footnote">
                Отсутствующая оценка учитывается отдельно от серой.
              </p>
            </>
          ) : (
            <p className="chart-empty">
              Источники банковских оценок не подтверждены.
            </p>
          )}
        </article>
        <article className="overview-panel">
          <h3>Наличие финансовых данных</h3>
          <p className="muted small">
            Компании с указанным значением за{" "}
            {comparison.financial_year || "выбранный год"}
          </p>
          {coverage.length ? (
            <div className="coverage-list">
              {coverage.map((item) => (
                <button
                  className="coverage-row"
                  key={item.key}
                  onClick={() =>
                    source({
                      title: `${item.label} · наличие данных за ${comparison.financial_year}`,
                      value: `Значение указано у ${item.available} из ${item.total} компаний. Не подтверждено или отсутствует: ${item.missing}. Ноль считается указанным значением.`,
                      evidence: item.evidence,
                    })
                  }
                >
                  <span>
                    <span>{item.label}</span>
                    <strong>
                      {item.available} <small>/ {item.total}</small>
                    </strong>
                  </span>
                  <span className="coverage-track" aria-hidden="true">
                    <span
                      style={{
                        width: `${(item.available / item.total) * 100}%`,
                      }}
                    />
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="chart-empty">
              Нет подтверждённого финансового периода для этой группы.
            </p>
          )}
          <p className="chart-footnote">
            Это наличие показателей, не рейтинг надёжности. Пропуски не
            считаются нулями.
          </p>
        </article>
      </div>
    </section>
  );
}
