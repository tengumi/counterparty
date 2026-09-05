/**
 * WEB-06: the company report and the basis behind one of its values.
 *
 * The checks follow the product rules rather than the layout: a value appears
 * only together with an existing basis, the four kinds of «no number» stay
 * distinguishable, and the external ЗСК signal keeps its raw value.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { CheckPage } from '../../pages/CheckPage';
import { getCompanyReport } from '../../mocks/reports';
import { findEvidence } from '../../mocks/workspace';
import { describeBankRisk, describeZsk, resolveFact } from './reportView';
import type { ReportFact } from '../../mocks/types';

const DEMO = '/checks/demo-project/chats/demo-thread';
const LOGISTICS = '/checks/logistics-project/chats/logistics-thread';
const NO_REPORT = '/checks/inn-project/chats/inn-thread';

function openCheck(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<CheckPage />} path="/checks/:projectId" />
        <Route element={<CheckPage />} path="/checks/:projectId/chats/:threadId" />
      </Routes>
    </MemoryRouter>,
  );
}

function panel() {
  return screen.getByRole('complementary', { name: 'Материалы проверки' });
}

/** Opens the report of one company through the panel of WEB-05. */
async function openReport(
  user: ReturnType<typeof userEvent.setup>,
  path: string,
  companyName: string | RegExp,
) {
  openCheck(path);
  await user.click(screen.getByRole('button', { name: 'Материалы' }));
  await user.click(within(panel()).getByRole('button', { name: companyName }));
}

/** Body of one report section, opened on request as in P1-02. */
async function openSection(user: ReturnType<typeof userEvent.setup>, title: RegExp) {
  const header = within(panel()).getByRole('button', { name: title });
  await user.click(header);
  const bodyId = header.getAttribute('aria-controls');
  return document.getElementById(bodyId ?? '') as HTMLElement;
}

describe('company report', () => {
  it('keeps a confirmed zero, an empty list, a missing block and a restricted one apart', async () => {
    const user = userEvent.setup();
    await openReport(user, DEMO, /Компания А/);

    const finance = await openSection(user, /Финансы/);
    // A zero written in the statement is a value, and says so.
    expect(within(finance).getByText('0 ₽')).toBeVisible();
    expect(within(finance).getByText(/подтверждённый ноль/)).toBeVisible();

    const executions = await openSection(user, /Взыскания/);
    expect(within(executions).getByText('В отчёте события не обнаружены')).toBeVisible();
    expect(within(executions).queryByText('0')).not.toBeInTheDocument();
    expect(within(executions).getByText(/не гарантия на будущее/)).toBeVisible();

    const activity = await openSection(user, /Деятельность и разрешения/);
    const licenses = within(activity).getByText('Лицензии').closest('div') as HTMLElement;
    expect(within(licenses).getByText('В отчёте нет этих сведений')).toBeVisible();
    expect(within(licenses).getByText(/не подтверждение, что событий не было/)).toBeVisible();

    const other = await openSection(user, /Другие сведения/);
    const beneficiaries = within(other)
      .getByText('Сведения о бенефициарах')
      .closest('div') as HTMLElement;
    expect(within(beneficiaries).getByText('Эти сведения недоступны')).toBeVisible();
    expect(
      within(beneficiaries).getByText(/не означает отсутствие риска/),
    ).toBeVisible();
  });

  it('states the availability of a section before it is opened', async () => {
    const user = userEvent.setup();
    await openReport(user, LOGISTICS, /Урал-Восток-Транзит/);

    const finance = within(panel()).getByRole('button', { name: /Финансы/ });
    expect(finance).toHaveAttribute('aria-expanded', 'false');
    expect(finance).toHaveTextContent('Раздела нет в отчёте');

    await user.click(finance);
    expect(screen.getByText(/Раздел не предоставлен в этом отчёте/)).toBeVisible();
  });

  it('opens a value into its basis and walks back to the report', async () => {
    const user = userEvent.setup();
    await openReport(user, DEMO, /Компания А/);
    await openSection(user, /Финансы/);

    await user.click(
      within(panel()).getByRole('button', { name: 'Основание: Капитал и резервы, 2025' }),
    );

    const detail = panel();
    expect(within(detail).getByRole('heading', { name: 'Основание 1' })).toBeVisible();
    expect(within(detail).getByText('−300 000 ₽')).toBeVisible();
    expect(within(detail).getByText('Компания А')).toBeVisible();
    expect(within(detail).getByText('2025 год, годовая отчётность')).toBeVisible();
    expect(
      within(detail).getByText('Предоставленный отчёт, раздел «Финансы»'),
    ).toBeVisible();
    expect(within(detail).getByText('5 августа 2026')).toBeVisible();
    // No first source of its own: the panel says so instead of inventing a link.
    expect(within(detail).getByText(/отдельной ссылки на реестр/)).toBeVisible();

    await user.click(within(detail).getByRole('button', { name: 'К отчёту' }));
    expect(screen.getByRole('heading', { name: 'Компания А' })).toBeVisible();
  });

  it('opens the file behind a basis that was read from a document', async () => {
    const user = userEvent.setup();
    openCheck(DEMO);

    await user.click(
      screen.getByRole('button', { name: 'Основание 4: Срок поставки по счёту' }),
    );
    await user.click(screen.getByRole('button', { name: 'Открыть документ' }));

    expect(screen.getByRole('heading', { name: 'Счёт-оферта.pdf' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'К основанию' }));
    expect(screen.getByRole('heading', { name: 'Основание 4' })).toBeVisible();
  });

  it('shows the raw ЗСК value as it arrived and never repaints it', async () => {
    const user = userEvent.setup();
    await openReport(user, LOGISTICS, /Транс-Лайн/);

    const zsk = within(panel()).getByText(/^ЗСК —/).closest('div') as HTMLElement;
    expect(zsk).toHaveTextContent('ЗСК — YELLOW');
    expect(zsk).toHaveTextContent('Исходное значение: YELLOW');
    expect(zsk).toHaveTextContent(/Отображение требует уточнения/);
    // Neither a translated colour nor an explanation of the closed methodology.
    expect(zsk).not.toHaveTextContent('Зелёный');
    expect(zsk).not.toHaveTextContent('Жёлтый');
    expect(zsk).not.toHaveTextContent('Средний');
  });

  it('says a company has no report instead of showing it as clean', async () => {
    const user = userEvent.setup();
    await openReport(user, NO_REPORT, /Компания по ИНН 7714497158/);

    expect(screen.getByText(/В демонстрационной базе нет отчёта/)).toBeVisible();
    expect(screen.getByText(/Это не проверка\s+без замечаний/)).toBeVisible();
  });

  it('puts a report row into the composer as a context chip', async () => {
    const user = userEvent.setup();
    await openReport(user, DEMO, /Компания А/);
    await openSection(user, /Финансы/);

    await user.click(
      within(panel()).getByRole('button', { name: 'Обсудить: Выручка, 2025' }),
    );

    expect(screen.getByLabelText('Сообщение помощнику')).toHaveValue(
      'Выручка, 2025 · Компания А · 2025 год, годовая отчётность',
    );
  });
});

describe('report presentation rules', () => {
  it('withholds a value whose basis cannot be resolved', () => {
    const dangling: ReportFact = {
      id: 'fact-dangling',
      label: 'Выручка, 2025',
      state: 'value',
      value: '74 586 000 ₽',
      note: null,
      evidenceId: 'ev-does-not-exist',
    };

    expect(resolveFact(dangling, findEvidence)).toEqual({ kind: 'withheld', fact: dangling });
  });

  it('resolves every row of every mock report into an existing basis', () => {
    for (const companyId of ['company-a', 'ural-vostok', 'trans-line']) {
      const report = getCompanyReport(companyId);
      expect(report).toBeDefined();
      for (const section of report!.sections) {
        for (const fact of section.facts) {
          expect(resolveFact(fact, findEvidence).kind).toBe('shown');
        }
      }
      expect(findEvidence(report!.zskRaw === '' ? null : report!.zskEvidenceId)).toBeDefined();
      expect(findEvidence(report!.bankRiskEvidenceId)).toBeDefined();
    }
  });

  it('keeps the raw ЗСК value and stays neutral for anything but a confirmed display', () => {
    expect(describeZsk('GREEN', 'ev').valueLabel).toBe('Зелёный');
    for (const raw of ['YELLOW', 'RED', 'UNSET']) {
      const signal = describeZsk(raw, 'ev');
      expect(signal.raw).toBe(raw);
      expect(signal.valueLabel).toBe(raw);
      expect(signal.tone).toBe('neutral');
      expect(signal.note).toMatch(/Отображение требует уточнения/);
    }
  });

  it('does not turn a missing bank assessment into a good one', () => {
    const unknown = describeBankRisk('UNKNOWN', 'ev');
    expect(unknown.valueLabel).toBe('Оценка недоступна');
    expect(unknown.tone).toBe('neutral');
    expect(unknown.note).toMatch(/не означает отсутствие риска/);
    expect(describeBankRisk('LOW', 'ev').valueLabel).toBe('Низкий');
  });
});
