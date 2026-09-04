import { useState } from "react";
import {
  Bar,
  ComposedChart,
  CartesianGrid,
  Cell,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Card } from "../types";
import type { SourceDetails } from "../components/EvidenceDrawer";
import {
  annualPoints,
  exactNumber,
  financialChartPoints,
  financialMetrics,
  type FinancialMetric,
} from "./chartData";

const axisNumber = (value: number) =>
  new Intl.NumberFormat("ru-RU", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);

export function CompanyFinancials({
  card,
  source,
}: {
  card: Card;
  source: (details: SourceDetails) => void;
}) {
  const [metric, setMetric] = useState<FinancialMetric>("proceeds");
  const [chartType, setChartType] = useState<"line" | "bar">("line");
  const periods = annualPoints(card);
  const latest = periods.at(-1);
  if (!latest)
    return (
      <div className="financial-empty">
        <strong>Финансовые показатели недоступны</strong>
        <p>
          В отчёте нет подтверждённых завершённых годовых периодов. Это не
          означает отсутствие деятельности.
        </p>
      </div>
    );
  const label = financialMetrics.find((item) => item.key === metric)!.label;
  const points = financialChartPoints(periods, metric);
  const showSource = (year: number, key: FinancialMetric) => {
    const point = periods.find((item) => item.year === year)!;
    source({
      title: `${financialMetrics.find((item) => item.key === key)!.label} · ${year}`,
      value:
        point.values[key] === null
          ? `Нет данных за ${year}. Пропуск не заменён нулём.`
          : `${exactNumber(point.values[key])} · единицы источника`,
      company: card.name,
      evidence: point.evidence,
    });
  };
  return (
    <section
      className="financial-overview"
      aria-label="Финансовые показатели компании"
    >
      <div className="visual-heading">
        <h3>Финансовые показатели</h3>
        <span className="period-chip">Последний период · {latest.year}</span>
      </div>
      <div className="metric-grid">
        {financialMetrics.map(({ key, label: title }) => (
          <button
            className="metric-card"
            key={key}
            onClick={() => showSource(latest.year, key)}
          >
            <span>
              {title}
              <span aria-hidden="true">↗</span>
            </span>
            <strong
              data-negative={latest.values[key]?.startsWith("-") || undefined}
            >
              {exactNumber(latest.values[key])}
            </strong>
            <small>
              {latest.values[key] === null
                ? "Не заменяем нулём"
                : "В единицах источника"}
            </small>
          </button>
        ))}
      </div>
      <div className="finance-chart-panel">
        <div className="visual-heading">
          <div>
            <h3>Значения по годам</h3>
            <p className="muted small">Только завершённые периоды отчёта</p>
          </div>
          <div className="finance-chart-controls">
            <div
              className="chart-type-switch"
              role="group"
              aria-label="Тип финансового графика"
            >
              <button
                type="button"
                aria-pressed={chartType === "line"}
                onClick={() => setChartType("line")}
              >
                Линия
              </button>
              <button
                type="button"
                aria-pressed={chartType === "bar"}
                onClick={() => setChartType("bar")}
              >
                Столбцы
              </button>
            </div>
            <select
              aria-label="Показатель на графике"
              value={metric}
              onChange={(event) =>
                setMetric(event.target.value as FinancialMetric)
              }
            >
              {financialMetrics.map(({ key, label: title }) => (
                <option key={key} value={key}>
                  {title}
                </option>
              ))}
            </select>
          </div>
        </div>
        <figure
          className="finance-figure"
          aria-label={`${chartType === "line" ? "Линейная" : "Столбчатая"} диаграмма: ${label}`}
        >
          {points.some((point) => point.plot !== null) ? (
            <ResponsiveContainer width="100%" height={225} minWidth={0}>
              <ComposedChart
                data={points}
                margin={{ top: 18, right: 12, left: 0, bottom: 0 }}
                accessibilityLayer
              >
                <CartesianGrid
                  vertical={false}
                  stroke="#e9edf3"
                  strokeDasharray="3 4"
                />
                <XAxis
                  dataKey="year"
                  tickLine={false}
                  axisLine={false}
                  padding={{ left: 20, right: 20 }}
                  tick={{ fill: "#687283", fontSize: 13 }}
                />
                <YAxis
                  tickFormatter={axisNumber}
                  tickLine={false}
                  axisLine={false}
                  width={70}
                  tick={{ fill: "#687283", fontSize: 12 }}
                />
                <ReferenceLine y={0} stroke="#aeb8c7" />
                <Tooltip
                  cursor={
                    chartType === "line"
                      ? { stroke: "#b8c7e0", strokeDasharray: "4 4" }
                      : { fill: "#edf2fc" }
                  }
                  filterNull={false}
                  content={({ active, payload }) => {
                    const point = payload?.[0]?.payload as
                      (typeof points)[number] | undefined;
                    return active && point ? (
                      <div className="chart-tooltip">
                        <span>
                          {label} · {point.year}
                        </span>
                        <strong>{exactNumber(point.exact)}</strong>
                        <small>
                          {point.exact === null
                            ? "Пропуск не заменён нулём"
                            : "Единицы источника"}
                        </small>
                      </div>
                    ) : null;
                  }}
                />
                {chartType === "line" ? (
                  <Line
                    type="linear"
                    dataKey="plot"
                    name={label}
                    stroke="#5076c5"
                    strokeWidth={2.5}
                    dot={{ r: 4, fill: "white", strokeWidth: 2.5 }}
                    activeDot={{ r: 6, stroke: "white", strokeWidth: 2 }}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                ) : (
                  <Bar
                    dataKey="plot"
                    name={label}
                    maxBarSize={54}
                    radius={[5, 5, 0, 0]}
                    isAnimationActive={false}
                  >
                    {points.map((point) => (
                      <Cell
                        key={point.year}
                        fill={
                          point.plot !== null && point.plot < 0
                            ? "#cf6269"
                            : "#5076c5"
                        }
                      />
                    ))}
                  </Bar>
                )}
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <p className="chart-empty">
              Нет значений, которые можно показать на шкале. Исходные данные —
              ниже.
            </p>
          )}
          <figcaption className="chart-disclaimer">
            Валюта и масштаб сумм не указаны; сопоставимость единиц между годами
            не подтверждена. Это значения отчёта, не оценка роста бизнеса.
          </figcaption>
        </figure>
        <div className="period-values" aria-label={`Точные значения: ${label}`}>
          {periods.map((point) => (
            <button
              key={point.year}
              onClick={() => showSource(point.year, metric)}
            >
              <span>
                {point.year} <span aria-hidden="true">↗</span>
              </span>
              <strong>{exactNumber(point.values[metric])}</strong>
            </button>
          ))}
        </div>
        <p className="chart-footnote">
          Пропуски не соединяются линией. Шкала округлена. Точные значения и их
          источники доступны по нажатию.
        </p>
      </div>
    </section>
  );
}
