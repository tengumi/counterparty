import { useState } from 'react';
import { Button } from '@alfalab/core-components/button';
import { Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ChartPoint, FinancialMetric } from '../financialView';
import { amountTone, axisAmount, chartUnit, financialMetrics } from '../financialView';
import { factText } from '../../liveReportView';
import styles from './FinancialChart.module.css';

const accent = 'var(--color-light-text-link, #2a77ef)';
const tones = {
  positive: 'var(--color-light-text-positive, #16824b)',
  negative: 'var(--color-light-text-negative, #d6242a)',
  neutral: accent,
};

export function MetricPicker({ value, onChange, label }: {
  value: FinancialMetric;
  onChange: (value: FinancialMetric) => void;
  label: string;
}) {
  return <label className={styles.picker}>
    <span className={styles.hidden}>{label}</span>
    <select value={value} onChange={(event) => onChange(event.target.value as FinancialMetric)}>
      {financialMetrics.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}
    </select>
  </label>;
}

export function FinancialChart({ points, metric, comparison = false, onEvidence, blocked }: {
  points: readonly ChartPoint[];
  metric: FinancialMetric;
  comparison?: boolean;
  onEvidence: (ref: string) => void;
  blocked?: string;
}) {
  const [kind, setKind] = useState<'line' | 'bar'>('line');
  const [selected, setSelected] = useState<string | null>(null);
  const unit = chartUnit(points);
  const present = points.filter((point) => point.value !== null);
  const message = blocked ?? (unit === null ? 'Валюта или единицы различаются. Значения доступны в таблице, но не объединены на одной шкале.'
    : !present.length ? 'Недостаточно числовых данных для графика. Доступные сведения остаются в таблице.' : null);
  const focused = points.find((point) => point.label === selected) ?? present.at(-1);
  const isBar = comparison || kind === 'bar';
  const metricLabel = financialMetrics.find((item) => item.key === metric)!.label;
  const color = (point: ChartPoint) => metric === 'profit' ? tones[amountTone(point.fact)] : accent;

  return <>
    <div className={styles.toolbar}>
      <span className={styles.unit}>{unit ?? 'Разные единицы'}{comparison ? '' : ' · по годам'}</span>
      {!comparison ? <div className={styles.switcher} role="group" aria-label="Вид финансового графика">
        <Button size={40} view="text" aria-pressed={kind === 'line'} onClick={() => setKind('line')}>Линия</Button>
        <Button size={40} view="text" aria-pressed={kind === 'bar'} onClick={() => setKind('bar')}>Столбцы</Button>
      </div> : null}
    </div>
    {message ? <div className={styles.empty} role="status">{message}</div> : <>
      <div className={styles.scroll}>
        <div className={styles.plot} style={{ height: comparison ? Math.max(240, points.length * 48 + 40) : 240 }}>
          <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 600, height: 240 }}>
            <ComposedChart data={[...points]} layout={comparison ? 'vertical' : 'horizontal'}
              margin={{ top: 16, right: 20, bottom: 4, left: 0 }} accessibilityLayer
              onClick={(state) => {
                if (state.activeLabel != null) setSelected(String(state.activeLabel));
              }}>
              <CartesianGrid stroke="var(--color-light-border-primary, #e7e8eb)" strokeDasharray="3 5" horizontal={!comparison} vertical={comparison} />
              {comparison ? <>
                <XAxis type="number" tickFormatter={axisAmount} tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: '#666b76' }}
                  domain={['auto', 'auto']} />
                <YAxis dataKey="label" type="category" width={116} tickLine={false} axisLine={false}
                  tickFormatter={(label: string) => {
                    const compact = label.replace(/^(\d+\.\s+)(?:ООО|ОАО|ЗАО|ПАО|АО)\s+["«]?/, '$1').replace(/["»]$/, '');
                    return compact.length > 14 ? `${compact.slice(0, 13)}…` : compact;
                  }}
                  tick={{ fontSize: 11, fill: '#454b56' }} interval={0} />
                <ReferenceLine x={0} stroke="#a4acb8" ifOverflow="extendDomain" />
              </> : <>
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: '#666b76' }} padding={{ left: 22, right: 22 }} minTickGap={24} />
                <YAxis width={76} tickLine={false} axisLine={false} tickFormatter={axisAmount} tick={{ fontSize: 11, fill: '#666b76' }}
                  domain={['auto', 'auto']} />
                <ReferenceLine y={0} stroke="#a4acb8" ifOverflow={isBar ? 'extendDomain' : 'discard'} />
              </>}
              <Tooltip cursor={isBar ? { fill: 'rgba(42, 119, 239, .045)' } : { stroke: '#a4acb8', strokeDasharray: '4 4' }}
                content={({ active, payload }) => {
                  const point = payload?.[0]?.payload as ChartPoint | undefined;
                  if (!active || !point?.fact) return null;
                  return <div className={styles.tooltip}>
                    <strong>{point.label}{comparison && point.fact.period ? ` · ${point.fact.period}` : ''}</strong>
                    <span>{metricLabel}</span>
                    <b data-amount-tone={metric === 'profit' ? amountTone(point.fact) : undefined}>{factText(point.fact)}</b>
                  </div>;
                }} />
              {isBar ? <Bar dataKey="value" name={metricLabel} maxBarSize={36} isAnimationActive={false} radius={4}>
                {points.map((point) => <Cell key={point.label} fill={color(point)} />)}
              </Bar> : <Line dataKey="value" name={metricLabel} type="linear" stroke={accent} strokeWidth={2.5}
                connectNulls={false} isAnimationActive={false}
                dot={(props) => {
                  const point = props.payload as ChartPoint;
                  return point.value === null ? <g key={point.label} />
                    : <circle key={point.label} cx={props.cx} cy={props.cy} r={4} fill={color(point)} stroke="white" strokeWidth={2} />;
                }} activeDot={{ r: 6, strokeWidth: 2, stroke: 'white' }} />}
              {isBar ? points.filter((point) => point.value === 0).map((point) => <ReferenceDot
                key={point.label} x={comparison ? 0 : point.label} y={comparison ? point.label : 0}
                r={3} fill={accent} stroke="white" />) : null}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </div>
      <div className={styles.readout}>
        <label className={styles.picker}>
          <span className={styles.hidden}>{comparison ? 'Компания для просмотра значения' : 'Год для просмотра значения'}</span>
          <select value={focused?.label ?? ''} onChange={(event) => setSelected(event.target.value)}>
            {points.map((point) => <option key={point.label} value={point.label}>{point.label}{comparison && point.fact?.period ? ` · ${point.fact.period}` : ''}</option>)}
          </select>
        </label>
        <span className={styles.exact} data-amount-tone={metric === 'profit' ? amountTone(focused?.fact) : undefined}>
          {focused?.fact ? factText(focused.fact) : 'Нет данных за этот период'}
        </span>
        {focused?.fact?.evidence_refs[0] ? <Button size={40} view="text"
          onClick={() => onEvidence(focused.fact!.evidence_refs[0]!)}
          aria-label={`Источник точки графика: ${metricLabel}, ${focused.label}`}>Источник</Button> : null}
      </div>
      <p className={styles.note}>
        {present.length < points.length ? 'Пропуски не заменены нулями. ' : ''}
        {isBar && points.some((point) => point.value === 0) ? 'Нулевое значение отмечено точкой. ' : ''}
        {!comparison && present.length === 1 ? 'Доступен один год — динамику оценить нельзя. ' : ''}
        {comparison ? 'Порядок компаний сохранён; график не является рейтингом.' : 'Точные значения и основания — в таблице и по выбранной точке.'}
      </p>
    </>}
  </>;
}
