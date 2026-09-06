import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { FinancialPeriod, ProjectComparison } from '../../../../api/reportContracts';
import { financeSection, overview, zeroFact, REF } from '../../../../test/reportFixtures';
import { ReportOverview } from '../ReportOverview';
import FinancialHistory from './FinancialHistory';
import ComparisonChart from './ComparisonChart';

describe('Финансовые графики и карточки', () => {
  it('переключает вид и показатель, открывает точный источник выбранной точки', async () => {
    const onEvidence = vi.fn();
    const period = financeSection.records[0] as FinancialPeriod;
    render(<FinancialHistory records={[{ ...period, profit: { ...zeroFact, key: 'profit', value: '-24.63' } }]} onEvidence={onEvidence} partial={false} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Столбцы' }));
    expect(screen.getByRole('button', { name: 'Столбцы' })).toHaveAttribute('aria-pressed', 'true');
    await user.selectOptions(screen.getByLabelText('Показатель динамики'), 'profit');
    expect(screen.getByRole('button', { name: 'Столбцы' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('-24,63 ₽')).toHaveAttribute('data-amount-tone', 'negative');
    await user.click(screen.getByRole('button', { name: 'Источник точки графика: Прибыль, 2025' }));
    expect(onEvidence).toHaveBeenCalledWith(REF);
    expect(screen.getByText(/Доступен один год/)).toBeVisible();
    await user.selectOptions(screen.getByLabelText('Показатель динамики'), 'cash');
    expect(screen.getByRole('status')).toHaveTextContent('Недостаточно числовых данных');
  });
  it.each([['12345.67', 'positive'], ['-12345.67', 'negative'], ['0.00', 'neutral']])('показывает знак прибыли %s в существующей краткой карточке', (value, tone) => {
    const report = { ...overview, facts: [zeroFact, { ...zeroFact, key: 'profit', value }] };
    const { container } = render(<ReportOverview report={report} onEvidence={vi.fn()} />);
    expect(container.querySelector('[data-amount-tone]')).toHaveAttribute('data-amount-tone', tone);
    expect(screen.getByRole('button', { name: 'Основание: Прибыль за 2025 год' })).toBeEnabled();
  });
  it('не строит сравнительную шкалу для разных лет', () => {
    const comparison: ProjectComparison = {
      schema_version: '0.1', id: null, project_id: 'project', report_ids: ['r1', 'r2'],
      criteria: ['financials'], year_policy: 'latest_available', year: null,
      proposal_facts: [], warnings: [], rule_version: '1',
      rows: [2024, 2025].map((period, index) => ({
        company: { ...overview.company, id: String(index) }, report: { ...overview.report, id: String(index) },
        cells: [{ ...zeroFact, period }], status: 'complete', warnings: [],
      })),
    };
    render(<ComparisonChart comparison={comparison} onEvidence={vi.fn()} />);
    expect(within(screen.getByRole('region', { name: 'Финансы в сравнении' })).getByRole('status')).toHaveTextContent('один и тот же год');
    expect(screen.queryByRole('application')).not.toBeInTheDocument();
  });
});
