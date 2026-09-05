import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import type { Browser, Page } from 'playwright-core';
import type { ApiProject } from '../src/api/contracts.ts';
import type { CompanyOverview, ProjectComparison, ReportEvidence, ReportSection } from '../src/api/reportContracts.ts';
import { startChrome } from './browser.ts';

const args = process.argv.slice(2);
const option = (key: string, fallback: string) => args.find((arg) => arg.startsWith(`${key}=`))?.slice(key.length + 1) ?? fallback;
const baseURL = option('--url', 'http://127.0.0.1:5173');
const output = resolve(option('--output', '../../artifacts/qa/WEB-08'));
const executable = option('--chrome', process.env.WEB08_CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
const matrix = ['create project and add two imported companies', 'pinned report/financial section/exact source and period', 'back, focus, draft and typed evidence context', 'server comparison and source return', 'reload retains pins, draft, context and comparison selection', 'desktop/mobile bounds, mobile keyboard and tablet overlay'];
interface Check { name: string; viewport: string; verdict: 'pass' | 'fail'; details?: string }
interface Capture { name: string; file: string; width: number; height: number; url: string }
const manifest = {
  scope: 'WEB-08', sourceSHA: '', sourceDirty: false, createdAt: new Date().toISOString(),
  browser: '', transport: 'Playwright connectOverCDP', baseURL, dataset: 'Live REST / approved imported mock snapshot; no browser interception',
  checks: [] as Check[], captures: [] as Capture[], projects: [] as { id: string; viewport: string; reportIds: string[] }[],
  requests: [] as { method: string; path: string; status: number }[], consoleErrors: [] as string[],
  limitations: ['Provided snapshots are mock source data, not current registry checks.', 'Agent conversation, documents and user decisions remain unavailable; this run does not certify WEB-09 or AG-04.', 'Comparison selection is persisted locally; no saved comparison artifact is claimed.', 'Desktop headless Chrome emulates mobile viewport/touch; native OS keyboard and 200% zoom are not covered.'],
};
function checked(name: string, viewport: string, condition: boolean, details?: string) {
  manifest.checks.push({ name, viewport, verdict: condition ? 'pass' : 'fail', details });
}
async function capture(page: Page, viewport: string, name: string) {
  await page.evaluate(() => document.fonts.ready);
  const size = page.viewportSize()!;
  const file = `${viewport}/${name}.png`;
  await mkdir(join(output, viewport), { recursive: true });
  await page.screenshot({ path: join(output, file) });
  manifest.captures.push({ name, file, ...size, url: page.url() });
}
async function bounds(page: Page, viewport: string, panelOpen: boolean) {
  const size = page.viewportSize()!;
  const metrics = await page.evaluate(() => ({ client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
  checked('No document horizontal overflow', viewport, metrics.scroll <= metrics.client + 1, JSON.stringify(metrics));
  if (panelOpen) {
    const panel = page.getByRole('complementary', { name: 'Материалы проверки' });
    const box = await panel.boundingBox();
    const expected = size.width <= 640 ? size.width : 400;
    checked('Panel has usable width and stays in viewport', viewport, !!box && Math.abs(box.width - expected) <= 1 && box.x >= -1 && box.y >= -1 && box.x + box.width <= size.width + 1 && box.y + box.height <= size.height + 1, JSON.stringify(box));
  } else {
    const box = await page.getByRole('textbox', { name: 'Сообщение помощнику' }).boundingBox();
    checked('Composer remains visible', viewport, !!box && box.y >= 0 && box.y + box.height <= size.height + 1, JSON.stringify(box));
  }
}
function numericText(text: string) {
  const value = text.replace(/[\s\u00a0\u202f]/g, '').replace(',', '.');
  return value.replace(/\.0+$/, '').replace(/(\.\d*?[1-9])0+$/, '$1');
}
async function scenario(browser: Browser, viewport: 'desktop' | 'mobile') {
  const size = viewport === 'mobile' ? { width: 390, height: 844 } : { width: 1440, height: 900 };
  const context = await browser.newContext({ viewport: size, locale: 'ru-RU', isMobile: viewport === 'mobile', hasTouch: viewport === 'mobile' });
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  page.on('pageerror', (error) => manifest.consoleErrors.push(`${viewport}: ${error.message}`));
  page.on('console', (message) => { if (message.type() === 'error') manifest.consoleErrors.push(`${viewport}: ${message.text()} (${message.location().url || "unknown location"})`); });
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (url.pathname.startsWith('/api/')) manifest.requests.push({ method: response.request().method(), path: url.pathname, status: response.status() });
  });
  try {
    const login = await context.request.post(`${baseURL}/api/v1/auth/session`, { data: { login: 'demo-analyst' } });
    assert.equal(login.status(), 201, await login.text());
    await page.goto(`${baseURL}/checks`);
    const title = `WEB-08 ${viewport} ${new Date().toISOString()}`;
    await page.getByRole('textbox', { name: 'Задача проверки' }).fill(title);
    await capture(page, viewport, 's1');
    await page.getByRole('button', { name: 'Отправить', exact: true }).click();
    await page.waitForURL(/\/checks\/[0-9a-f-]{36}(?:\/chats\/[0-9a-f-]{36})?$/);
    const projectId = new URL(page.url()).pathname.split('/')[2]!;
    const composer = page.getByRole('textbox', { name: 'Сообщение помощнику' });
    await composer.waitFor();
    const draft = `Проверить аванс, сохранить основание — ${viewport}`;
    await composer.fill(draft);
    if (viewport === 'mobile') {
      await composer.press('End');
      await composer.press('Enter');
      checked('Mobile Enter inserts newline', viewport, await composer.inputValue() === `${draft}\n`);
      await composer.fill(draft);
    }
    checked('Unavailable agent is explicit; draft remains editable', viewport, await page.getByRole('button', { name: 'Отправить', exact: true }).isDisabled() && await page.getByText('История разговора пока недоступна.', { exact: true }).isVisible());
    await bounds(page, viewport, false);
    const materials = page.getByRole('button', { name: 'Материалы', exact: true });
    await materials.click();
    const panel = page.getByRole('complementary', { name: 'Материалы проверки' });
    await panel.getByRole('textbox', { name: 'ИНН компаний' }).fill('1684017097\n7449088645');
    const addition = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith(`/projects/${projectId}/companies`));
    await panel.getByRole('button', { name: 'Добавить компании', exact: true }).click();
    assert.equal((await addition).status(), 200);
    await panel.getByRole('button', { name: /ИНН 1684017097/ }).waitFor();
    const saved = await context.request.get(`${baseURL}/api/v1/projects/${projectId}`);
    assert.equal(saved.status(), 200);
    const project = await saved.json() as ApiProject;
    assert.equal(project.companies.length, 2);
    const company = project.companies.find((item) => item.inn === '1684017097')!;
    const reportIds = project.companies.map((item) => item.report_id);
    manifest.projects.push({ id: projectId, viewport, reportIds });
    checked('Created server project and pinned two reports', viewport, reportIds.every((id) => /^[0-9a-f-]{36}$/.test(id)), projectId);
    await bounds(page, viewport, true);
    await capture(page, viewport, 'materials');
    if (viewport === 'desktop') {
      await page.setViewportSize({ width: 1024, height: 768 });
      await bounds(page, 'tablet', true);
      await capture(page, 'tablet', 'materials');
      await page.setViewportSize(size);
    }
    const overviewResponse = page.waitForResponse((response) => response.url().endsWith(`/reports/${company.report_id}/overview`));
    await panel.getByRole('button', { name: /ИНН 1684017097/ }).click();
    const overview = await (await overviewResponse).json() as CompanyOverview;
    assert.equal(overview.report.id, company.report_id);
    await panel.getByText(/Предоставленный учебный снимок/).waitFor();
    checked('Report is pinned and displays raw ZSK', viewport, overview.zsk.raw_value == null || (await panel.innerText()).includes(overview.zsk.raw_value));
    const sectionResponse = page.waitForResponse((response) => response.url().includes(`/reports/${company.report_id}/sections/financials?`));
    await panel.getByRole('button', { name: /^Финансы/ }).click();
    const section = await (await sectionResponse).json() as ReportSection;
    const record = section.records.find((item) => item.kind === 'financial_period' && item.proceeds.availability === 'available');
    assert.ok(record?.kind === 'financial_period');
    const sourceRef = record.proceeds.evidence_refs[0]!;
    const fact = panel.locator('[class*="factRow"]').filter({ has: page.getByRole('button', { name: 'Основание: Выручка', exact: true }) }).first();
    await fact.waitFor();
    const shown = await fact.locator('[class*="rowName"]').innerText();
    checked('Financial amount and year match server DTO', viewport, numericText(shown.replace(/₽|руб\.?/g, '')) === numericText(String(record.proceeds.value)) && (await fact.innerText()).includes(`${record.year} год`), `period=${record.year}; report_id=${company.report_id}`);
    await capture(page, viewport, 'report');
    const evidenceResponse = page.waitForResponse((response) => response.url().includes(`/projects/${projectId}/evidence/`));
    await fact.getByRole('button', { name: 'Основание: Выручка', exact: true }).click();
    const evidence = await (await evidenceResponse).json() as ReportEvidence;
    assert.equal(evidence.evidence.id, sourceRef);
    assert.equal(evidence.report.id, company.report_id);
    await panel.getByText('Дата среза', { exact: true }).waitFor();
    checked('Evidence resolves exact report ref and period', viewport, evidence.evidence.period === record.year && (await panel.locator('dl').innerText()).includes(String(record.year)), sourceRef);
    checked('Evidence source fragment is rendered', viewport, await panel.locator('[aria-label="Исходный фрагмент"]').isVisible());
    await bounds(page, viewport, true);
    await capture(page, viewport, 'evidence');
    await panel.getByRole('button', { name: 'К отчёту', exact: true }).click();
    await fact.getByRole('button', { name: 'Обсудить: Выручка', exact: true }).click();
    await panel.waitFor({ state: 'hidden' });
    checked('Discuss restores draft focus without sending', viewport, await composer.inputValue() === draft && await composer.evaluate((element) => element === document.activeElement));
    const chips = page.locator('[aria-label="Материалы в черновике"]');
    checked('Evidence context chip is present', viewport, (await chips.innerText()).includes('Выручка'));
    await materials.click();
    await panel.getByRole('button', { name: 'К материалам', exact: true }).click();
    await panel.getByRole('button', { name: 'Сравнить компании', exact: true }).click();
    await panel.getByRole('combobox', { name: 'Финансовый период' }).selectOption('explicit');
    await panel.getByRole('spinbutton', { name: 'Год сравнения' }).fill(String(record.year));
    const comparisonResponse = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith(`/projects/${projectId}/comparisons`));
    await panel.getByRole('button', { name: 'Сравнить выбранные (2)', exact: true }).click();
    const response = await comparisonResponse;
    assert.equal(response.status(), 200);
    const comparison = await response.json() as ProjectComparison;
    const submitted = response.request().postDataJSON() as { report_ids: string[]; year: number; year_policy: string };
    checked('Comparison is computed by server for pinned reports/year', viewport, comparison.rows.length === 2 && JSON.stringify(submitted.report_ids) === JSON.stringify(reportIds) && submitted.year === record.year && submitted.year_policy === 'explicit');
    const result = panel.getByRole('region', { name: 'Результат сравнения' });
    await result.getByRole('heading', { name: 'Сравнение 2 компаний', exact: true }).waitFor();
    checked('All server company rows appear', viewport, await result.locator('tbody tr').count() === comparison.rows.length);
    await result.scrollIntoViewIfNeeded();
    await bounds(page, viewport, true);
    await capture(page, viewport, 'comparison');
    await result.getByRole('button', { name: /^Основание:/ }).first().click();
    await panel.getByText('Дата среза', { exact: true }).waitFor();
    await panel.getByRole('button', { name: 'К сравнению', exact: true }).click();
    await panel.getByRole('button', { name: 'Обсудить сравнение', exact: true }).click();
    await panel.waitFor({ state: 'hidden' });
    checked('Comparison context retains draft', viewport, (await chips.innerText()).includes('Сравнение 2 компаний') && await composer.inputValue() === draft);
    await page.reload();
    await composer.waitFor();
    checked('Reload retains draft and both typed contexts', viewport, await composer.inputValue() === draft && (await chips.innerText()).includes('Выручка') && (await chips.innerText()).includes('Сравнение 2 компаний'));
    await bounds(page, viewport, false);
    await capture(page, viewport, 'draft-reloaded');
    await materials.click();
    await panel.getByRole('heading', { name: 'Сравнение 2 компаний', exact: true }).waitFor();
    checked('Reload restores comparison selection/result from REST', viewport, await panel.getByRole('combobox', { name: 'Финансовый период' }).inputValue() === 'explicit' && await panel.getByRole('spinbutton', { name: 'Год сравнения' }).inputValue() === String(record.year));
    await panel.getByRole('button', { name: 'Назад к разговору — закрыть материалы', exact: true }).click();
    checked('Close returns focus to materials opener', viewport, await materials.evaluate((element) => element === document.activeElement));
    checked('No chat message sent by discussion actions', viewport, !manifest.requests.some((request) => request.method === 'POST' && request.path.includes('/messages')));
  } catch (error) {
    checked('Complete live flow', viewport, false, error instanceof Error ? error.message : String(error));
    await capture(page, viewport, 'failure').catch(() => undefined);
  } finally { await context.close(); }
}

if (!args.includes('--capture')) {
  console.log(JSON.stringify({ scope: 'WEB-08', matrix, browserStarted: false, next: 'npm run qa:web08 -- --capture' }, null, 2));
} else {
  manifest.sourceSHA = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  manifest.sourceDirty = execFileSync('git', ['status', '--porcelain', '--', '../..', ':!../../artifacts/qa/WEB-08'], { encoding: 'utf8' }).trim().length > 0;
  if (manifest.sourceDirty) throw new Error('Commit reviewed source before the final capture');
  await mkdir(output, { recursive: true });
  const chrome = await startChrome(executable);
  manifest.browser = chrome.browser.version();
  try {
    for (const viewport of ['desktop', 'mobile'] as const) await scenario(chrome.browser, viewport);
  } finally {
    await writeFile(join(output, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
    await chrome.close();
  }
  const failures = manifest.checks.filter((check) => check.verdict === 'fail');
  console.log(JSON.stringify({ sourceSHA: manifest.sourceSHA, checks: manifest.checks.length, captures: manifest.captures.length, failures, consoleErrors: manifest.consoleErrors, output }, null, 2));
  if (failures.length || manifest.consoleErrors.length) process.exitCode = 1;
}
