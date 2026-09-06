import { Button } from '@alfalab/core-components/button';
import type { Assessment, CompanyOverview } from '../../../api/reportContracts';
import { availabilityText, factText } from '../liveReportView';
import styles from './Report.module.css';
import { amountTone, metricFact } from './financialView';

const signalLabels: Record<string, string> = {
  LOW: 'Низкий риск', MEDIUM: 'Средний риск', HIGH: 'Высокий риск',
  GREEN: 'Зелёный', YELLOW: 'Жёлтый', RED: 'Красный',
};

export function ReportOverview({ report, onEvidence }: {
  report: CompanyOverview;
  onEvidence: (ref: string) => void;
}) {
  const signal = (label: string, value: Assessment, note: string) => ({
    label,
    value: value.availability === 'available' && value.evidence_refs.length
      ? signalLabels[value.raw_value ?? ''] ?? value.raw_value ?? 'Нет сведений'
      : availabilityText[value.availability],
    note,
    ref: value.evidence_refs[0],
    tone: value.display_level,
  });
  const financial = (key: string, label: string) => {
    const facts = report.facts.filter((fact) => fact.key.split(/[./]/).at(-1) === key)
      .sort((a, b) => Number(b.period) - Number(a.period));
    const current = facts[0];
    return {
      label: `${label}${current?.period ? ` за ${current.period} год` : ''}`,
      value: current ? factText(current) : 'Нет сведений',
      note: facts.slice(1, 3).map((fact) => `${fact.period}: ${factText(fact)}`).join(' · ') || 'Из финансовой отчётности',
      ref: current?.evidence_refs[0],
      tone: undefined,
    };
  };
  const sectionCard = (section: string, label: string) => {
    const item = report.available_sections.find((entry) => entry.section === section);
    return {
      label,
      value: item?.availability === 'available' ? 'Сведения предоставлены' : item ? availabilityText[item.availability] : 'Нет сведений',
      note: 'Подробности в разделе ниже',
      ref: item?.evidence_refs[0],
      tone: undefined,
    };
  };
  const cards = [
    signal('Оценка банка', report.bank_risk, 'Самостоятельная оценка источника, не оценка финансового положения'),
    signal('Проверка операций (ЗСК)', report.zsk, 'Отдельная оценка, с оценкой банка не складывается'),
    financial('proceeds', 'Выручка'),
    financial('equity', 'Свои средства'),
    sectionCard('execution_proceedings', 'Долги у приставов'),
    sectionCard('arbitration', 'Судебные споры'),
    sectionCard('licenses', 'Лицензии'),
    sectionCard('risk_signals', 'Сигналы источника'),
  ];
  const profit = metricFact(report.facts, 'profit');
  return <div className={styles.metrics}>
    {cards.map((card, index) => <div className={styles.metric} key={card.label}>
      <div className={styles.metricHeading}>
        <span>{card.label}</span>
        {card.ref ? <Button size={32} view="text" aria-label={`Основание: ${card.label}`}
          onClick={() => onEvidence(card.ref as string)}>
          <span className={styles.helpIcon} aria-hidden="true">?</span>
        </Button> : null}
      </div>
      <div className={styles.metricValue}>
        {card.tone ? <span className={`${styles.dot} ${styles[card.tone]}`} /> : null}
        {card.value}
      </div>
      <p>{card.note}</p>
      {index === 2 ? <div className={styles.profitLine}>
        <span>Прибыль{profit?.period ? ` · ${profit.period}` : ''}</span>
        <span className={styles.profitValue} data-amount-tone={amountTone(profit)}>
          {profit ? factText(profit) : 'Нет сведений'}
        </span>
        {profit?.evidence_refs[0] ? <Button size={32} view="text"
          aria-label={`Основание: Прибыль${profit.period ? ` за ${profit.period} год` : ''}`}
          onClick={() => onEvidence(profit.evidence_refs[0]!)}>
          <span className={styles.helpIcon} aria-hidden="true">?</span>
        </Button> : null}
      </div> : null}
    </div>)}
  </div>;
}
