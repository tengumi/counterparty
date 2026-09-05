import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { Browser, Page } from 'playwright-core';
import type { DataSource, Manifest, Viewport } from './config.ts';
import { viewports } from './config.ts';
import { installFixtures } from './fixtures.ts';

interface Run {
  browser: Browser;
  manifest: Manifest;
  output: string;
  baseURL: string;
}

function check(run: Run, viewport: Viewport, source: DataSource, name: string, pass: boolean, details?: string) {
  run.manifest.checks.push({ name, viewport: viewport.name, source, verdict: pass ? 'pass' : 'fail', details });
}

async function capture(run: Run, page: Page, viewport: Viewport, source: DataSource, name: string) {
  await page.evaluate(() => document.fonts.ready);
  const file = `${source}/${viewport.name}/${name}.png`;
  await mkdir(dirname(join(run.output, file)), { recursive: true });
  await page.screenshot({ path: join(run.output, file), animations: 'disabled', fullPage: false });
  run.manifest.captures.push({ name, file, viewport: { width: viewport.width, height: viewport.height }, source, url: page.url() });
}

async function noOverflow(run: Run, page: Page, viewport: Viewport, source: DataSource, label: string) {
  const dimensions = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }));
  check(run, viewport, source, `${label}: no horizontal overflow`, dimensions.content <= dimensions.viewport + 1, JSON.stringify(dimensions));
}

async function keyTargets(run: Run, page: Page, viewport: Viewport) {
  if (viewport.name !== 'mobile') return;
  for (const name of ['Материалы', 'Чат: Поставка']) {
    const box = await page.getByRole('button', { name, exact: true }).boundingBox();
    check(run, viewport, 'typed-fixtures', `${name}: mobile target >=44px`, !!box && box.width >= 44 && box.height >= 44, JSON.stringify(box));
  }
}

async function caseRun(run: Run, viewport: Viewport, source: DataSource, name: string, action: () => Promise<void>) {
  try {
    await action();
  } catch (error) {
    check(run, viewport, source, name, false, error instanceof Error ? error.message : String(error));
  }
}

async function makePage(run: Run, viewport: Viewport) {
  const context = await run.browser.newContext({ viewport: { width: viewport.width, height: viewport.height }, locale: 'ru-RU', timezoneId: 'Europe/Moscow', deviceScaleFactor: 1, reducedMotion: 'reduce' });
  const page = await context.newPage();
  page.setDefaultTimeout(7000);
  page.on('pageerror', (error) => { run.manifest.consoleErrors.push(`${viewport.name}: ${error.message}`); });
  // 503 is intentional in failure scenarios; JS exceptions are recorded separately above.
  return { context, page };
}

async function mainFixtures(run: Run, viewport: Viewport) {
  const { context, page } = await makePage(run, viewport);
  const fixtures = await installFixtures(page);
  try {
    await caseRun(run, viewport, 'typed-fixtures', 'S1 populated and keyboard', async () => {
      await page.goto(`${run.baseURL}/checks`);
      await page.getByRole('link', { name: /Поставка оборудования/ }).waitFor();
      await capture(run, page, viewport, 'typed-fixtures', 's1-populated');
      await noOverflow(run, page, viewport, 'typed-fixtures', 'S1');
      const composer = page.getByRole('textbox', { name: 'Задача проверки' });
      check(run, viewport, 'typed-fixtures', 'S1 empty send disabled', await page.getByRole('button', { name: 'Отправить', exact: true }).isDisabled());
      await page.getByRole('button', { name: 'Хочу проверить поставщика', exact: true }).click();
      check(run, viewport, 'typed-fixtures', 'Example only inserts editable text', (await composer.inputValue()).includes('Хочу проверить поставщика') && fixtures.requests.every((request) => !request.startsWith('POST')));
      await composer.focus();
      await composer.press('End');
      await composer.press('Shift+Enter');
      check(run, viewport, 'typed-fixtures', 'Shift+Enter inserts newline', (await composer.inputValue()).includes('\n'));
      const draft = await composer.inputValue();
      fixtures.state.submitFails = true;
      await composer.press('Enter');
      await page.getByRole('alert').waitFor();
      check(run, viewport, 'typed-fixtures', 'Submit failure retains draft', (await composer.inputValue()) === draft && fixtures.requests.filter((request) => request === 'POST /api/v1/projects').length === 1);
    });

    await caseRun(run, viewport, 'typed-fixtures', 'S2/panels/draft/scroll/focus', async () => {
      await page.goto(`${run.baseURL}/checks/demo-project/chats/demo-thread`);
      const composer = page.getByRole('textbox', { name: 'Сообщение помощнику' });
      await composer.waitFor();
      const feed = page.locator('[class*="feedScroll"]');
      await feed.evaluate((element) => { element.scrollTop = 0; });
      await capture(run, page, viewport, 'typed-fixtures', 's2-conversation');
      await noOverflow(run, page, viewport, 'typed-fixtures', 'S2');
      await keyTargets(run, page, viewport);
      const measurements = await feed.evaluate((element) => ({ client: element.clientHeight, scroll: element.scrollHeight }));
      const inputBox = await composer.boundingBox();
      check(run, viewport, 'typed-fixtures', 'Feed bounded and independently scrollable', measurements.scroll > measurements.client && measurements.client > 0, JSON.stringify(measurements));
      check(run, viewport, 'typed-fixtures', 'Composer visible in viewport', !!inputBox && inputBox.y + inputBox.height <= viewport.height, JSON.stringify(inputBox));
      await composer.fill('WEB-07: сохранённый черновик');
      await feed.evaluate((element) => { element.scrollTop = Math.min(140, (element.scrollHeight - element.clientHeight) / 2); element.dispatchEvent(new Event('scroll')); });
      const refTargets = await page.locator('button[aria-label^="Основание "]').evaluateAll((elements) => elements.map((element) => {
        const rect = element.getBoundingClientRect();
        const target = getComputedStyle(element, '::after');
        return { label: element.getAttribute('aria-label'), x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, width: Number.parseFloat(target.width), height: Number.parseFloat(target.height) };
      }));
      const overlaps = refTargets.flatMap((a, index) => refTargets.slice(index + 1).filter((b) => Math.abs(a.x - b.x) < (a.width + b.width) / 2 && Math.abs(a.y - b.y) < (a.height + b.height) / 2).map((b) => [a.label, b.label]));
      check(run, viewport, 'typed-fixtures', 'Evidence expanded targets >=44px and do not overlap', refTargets.every((target) => target.width >= 44 && target.height >= 44) && overlaps.length === 0, JSON.stringify({ overlaps }));
      const originalScroll = await feed.evaluate((element) => element.scrollTop);
      const materials = page.getByRole('button', { name: 'Материалы', exact: true });
      await materials.focus();
      await materials.press('Enter');
      const panel = page.getByRole('complementary', { name: 'Материалы проверки' });
      await panel.waitFor();
      await capture(run, page, viewport, 'typed-fixtures', 'materials');
      await noOverflow(run, page, viewport, 'typed-fixtures', 'P1');
      const panelBox = await panel.boundingBox();
      check(run, viewport, 'typed-fixtures', 'P1 width follows breakpoint', !!panelBox && Math.abs(panelBox.width - (viewport.name === 'mobile' ? viewport.width : 400)) <= 1, JSON.stringify(panelBox));
      check(run, viewport, 'typed-fixtures', 'Panel heading receives keyboard focus', await panel.locator('h2').evaluate((element) => element === document.activeElement));
      if (viewport.name === 'mobile') {
        const close = panel.getByRole('button', { name: 'Назад к разговору — закрыть материалы', exact: true });
        check(run, viewport, 'typed-fixtures', 'Mobile close accessible name includes visible label', (await close.getAttribute('aria-label'))?.toLocaleLowerCase('ru').includes((await close.innerText()).trim().toLocaleLowerCase('ru')) ?? false);
      }
      await panel.getByRole('button', { name: /Компания А.*ИНН/ }).click();
      await panel.getByText('Учебный пример.', { exact: false }).waitFor();
      if (viewport.name !== 'tablet') await capture(run, page, viewport, 'typed-fixtures', 'report');
      await panel.getByRole('button', { name: /^Финансы/ }).click();
      check(run, viewport, 'typed-fixtures', 'Report confirmed zero is explicit', await panel.getByText('0 ₽', { exact: true }).isVisible());
      for (const [section, expected] of [
        ['Взыскания', 'В отчёте события не обнаружены'],
        ['Деятельность и разрешения', 'В отчёте нет этих сведений'],
        ['Другие сведения', 'Эти сведения недоступны'],
      ] as const) {
        await panel.getByRole('button', { name: new RegExp(`^${section}`) }).click();
        check(run, viewport, 'typed-fixtures', `${section}: source state remains distinct`, await panel.getByText(expected, { exact: true }).first().isVisible());
      }
      await panel.getByRole('button', { name: 'Основание: Капитал и резервы, 2025', exact: true }).click();
      await panel.getByRole('heading', { name: 'Основание 1', exact: true }).waitFor();
      if (viewport.name !== 'tablet') await capture(run, page, viewport, 'typed-fixtures', 'evidence');
      check(run, viewport, 'typed-fixtures', 'Evidence includes company/period/source/as-of', await panel.getByText('Дата среза', { exact: true }).isVisible() && await panel.getByText('Компания А', { exact: true }).isVisible());
      await panel.getByRole('button', { name: 'К отчёту', exact: true }).click();
      await panel.getByRole('button', { name: 'К материалам', exact: true }).click();
      await panel.getByRole('button', { name: 'Назад к разговору — закрыть материалы', exact: true }).click();
      check(run, viewport, 'typed-fixtures', 'Closing panel restores opener focus', await materials.evaluate((element) => element === document.activeElement));
      check(run, viewport, 'typed-fixtures', 'Closing panel retains draft', await composer.inputValue() === 'WEB-07: сохранённый черновик');
      const afterScroll = await feed.evaluate((element) => element.scrollTop);
      check(run, viewport, 'typed-fixtures', 'Panel round-trip preserves earlier scroll', Math.abs(afterScroll - originalScroll) <= 2, `${originalScroll} -> ${afterScroll}`);

      const switcher = page.getByRole('button', { name: 'Чат: Поставка', exact: true });
      await switcher.click();
      if (viewport.name === 'mobile') await capture(run, page, viewport, 'typed-fixtures', 'chat-switcher');
      await page.keyboard.press('Escape');
      check(run, viewport, 'typed-fixtures', 'Switcher Escape returns focus', await switcher.evaluate((element) => element === document.activeElement));
      const outline = await switcher.evaluate((element) => ({ visible: element.matches(':focus-visible'), style: getComputedStyle(element).outlineStyle, width: getComputedStyle(element).outlineWidth }));
      check(run, viewport, 'typed-fixtures', 'Keyboard focus visibly styled', outline.visible && outline.style !== 'none' && outline.width !== '0px', JSON.stringify(outline));
      await switcher.press('Enter');
      await page.getByRole('button', { name: /^Условия оплаты.*Сопоставляю/ }).click();
      await page.getByRole('button', { name: 'Чат: Условия оплаты', exact: true }).click();
      await page.getByRole('button', { name: /^Поставка.*Ждём подтверждение/ }).click();
      check(run, viewport, 'typed-fixtures', 'Chat switch restores draft', await composer.inputValue() === 'WEB-07: сохранённый черновик');
      check(run, viewport, 'typed-fixtures', 'Chat switch restores earlier scroll', Math.abs(await feed.evaluate((element) => element.scrollTop) - originalScroll) <= 2);
      await page.reload();
      await composer.waitFor();
      check(run, viewport, 'typed-fixtures', 'Reload restores draft', await composer.inputValue() === 'WEB-07: сохранённый черновик');
      // Wait for real font/layout/ResizeObserver cycles, not an arbitrary timeout.
      await page.evaluate(async () => { await document.fonts.ready; await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))); });
      const reloadedScroll = await feed.evaluate((element) => element.scrollTop);
      check(run, viewport, 'typed-fixtures', 'Reload and initial resize preserve earlier scroll', Math.abs(reloadedScroll - originalScroll) <= 2, `${originalScroll} -> ${reloadedScroll}`);

      const evidenceCases = [
        { number: 1, id: 'ev-capital', value: '−300 000 ₽' },
        { number: 2, id: 'ev-executions', value: 'В отчёте события не обнаружены' },
        { number: 3, id: 'ev-age', value: '16 апреля 2009' },
        { number: 4, id: 'ev-offer', value: '21 день после комплектации заказа' },
      ];
      for (const evidence of evidenceCases) {
        const ref = page.getByRole('button', { name: new RegExp(`^Основание ${evidence.number}:`) });
        await ref.scrollIntoViewIfNeeded();
        const box = await ref.boundingBox();
        assert.ok(box);
        await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
        await panel.getByRole('heading', { name: `Основание ${evidence.number}`, exact: true }).waitFor();
        const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('counterparty.s2.materials:demo-project') ?? '{}') as { stack?: { evidenceId?: string }[] });
        check(run, viewport, 'typed-fixtures', `Evidence ${evidence.number} center resolves correct source`, stored.stack?.at(-1)?.evidenceId === evidence.id && await panel.getByText(evidence.value, { exact: true }).isVisible(), `expected=${evidence.id}; actual=${stored.stack?.at(-1)?.evidenceId}`);
        await panel.getByRole('button', { name: 'Назад к разговору — закрыть материалы', exact: true }).click();
      }
      await page.getByRole('button', { name: /^Основание 4:/ }).click();
      await panel.getByRole('button', { name: 'Открыть документ', exact: true }).click();
      check(run, viewport, 'typed-fixtures', 'Document source opens honest unavailable preview', await panel.getByText('Просмотр файла появится', { exact: false }).isVisible());
      await panel.getByRole('button', { name: 'К основанию', exact: true }).click();
      await panel.getByRole('button', { name: 'Назад к разговору — закрыть материалы', exact: true }).click();
    });

    if (viewport.name === 'mobile') {
      await caseRun(run, viewport, 'typed-fixtures', 'Long names', async () => {
        await page.goto(`${run.baseURL}/checks/logistics-project/chats/logistics-thread`);
        await page.getByRole('button', { name: 'Материалы', exact: true }).click();
        const panel = page.getByRole('complementary', { name: 'Материалы проверки' });
        await panel.getByRole('button', { name: /Специализированная транспортно-логистическая/ }).click();
        await capture(run, page, viewport, 'typed-fixtures', 'long-name');
        await noOverflow(run, page, viewport, 'typed-fixtures', 'Long-name P1');
        await panel.getByRole('button', { name: 'Назад к разговору — закрыть материалы', exact: true }).click();
      });
    }
    await caseRun(run, viewport, 'typed-fixtures', '200% text zoom', async () => {
      await page.goto(`${run.baseURL}/checks`);
      await page.getByRole('textbox', { name: 'Задача проверки' }).waitFor();
      // Browser emulation of text-only zoom: double computed text sizes, preserve layout widths.
      await page.evaluate(() => {
        const nodes = [...document.querySelectorAll<HTMLElement>('body *')];
        const sizes = nodes.map((node) => Number.parseFloat(getComputedStyle(node).fontSize));
        nodes.forEach((node, index) => { node.style.fontSize = `${sizes[index]! * 2}px`; });
      });
      await noOverflow(run, page, viewport, 'typed-fixtures', '200% text zoom S1');
      const send = page.getByRole('button', { name: 'Отправить', exact: true });
      check(run, viewport, 'typed-fixtures', '200% text zoom retains send control', await send.isVisible());
    });
  } finally {
    await fixtures.release();
    await context.close();
  }
}

async function stateFixtures(run: Run) {
  const viewport = viewports[2];
  for (const state of ['empty', 'loading', 'error'] as const) {
    const { context, page } = await makePage(run, viewport);
    const fixtures = await installFixtures(page);
    fixtures.state.list = state;
    try {
      await caseRun(run, viewport, 'typed-fixtures', `S1 ${state}`, async () => {
        await page.goto(`${run.baseURL}/checks`, { waitUntil: 'domcontentloaded' });
        const expected = state === 'empty' ? 'Здесь появятся ваши проверки' : state === 'loading' ? 'Загружаем проверки…' : 'Это не означает, что сохранённых проверок нет.';
        await page.getByText(expected, { exact: true }).waitFor();
        await capture(run, page, viewport, 'typed-fixtures', `s1-${state}`);
        check(run, viewport, 'typed-fixtures', `S1 ${state} distinct from empty`, state === 'empty' || await page.getByText('Здесь появятся ваши проверки', { exact: true }).count() === 0);
        if (state === 'error') {
          fixtures.state.list = 'populated';
          await page.getByRole('button', { name: 'Повторить', exact: true }).click();
          await page.getByRole('link', { name: /Поставка оборудования/ }).waitFor();
          check(run, viewport, 'typed-fixtures', 'List error retry recovers', true);
        }
      });
    } finally { await fixtures.release(); await context.close(); }
  }
}

export async function runFixtures(run: Run) {
  for (const viewport of viewports) await mainFixtures(run, viewport);
  await stateFixtures(run);
}

export async function runLive(run: Run) {
  const viewport = viewports[2];
  const { context, page } = await makePage(run, viewport);
  try {
    await caseRun(run, viewport, 'live-rest', 'Live REST CRUD', async () => {
      const login = await context.request.post(`${run.baseURL}/api/v1/auth/session`, { data: { login: 'demo-analyst' } });
      assert.equal(login.status(), 201, await login.text());
      await page.goto(`${run.baseURL}/checks`);
      const title = `WEB-07 browser CRUD ${new Date().toISOString()}`;
      await page.getByRole('textbox', { name: 'Задача проверки' }).fill(title);
      await page.getByRole('button', { name: 'Отправить', exact: true }).click();
      await page.waitForURL(/\/checks\/[^/]+\/chats\/[^/]+$/);
      const projectId = new URL(page.url()).pathname.split('/')[2]!;
      assert.match(projectId, /^[0-9a-f-]{36}$/);
      const renamed = `${title} — проверено`;
      await page.getByRole('button', { name: 'Переименовать проверку', exact: true }).click();
      const titleInput = page.getByRole('textbox', { name: 'Название проверки', exact: true });
      await titleInput.fill(renamed);
      await titleInput.press('Enter');
      await page.getByRole('button', { name: 'Переименовать проверку', exact: true }).filter({ hasText: renamed }).waitFor();
      const directory = await context.request.get(`${run.baseURL}/api/v1/companies?limit=2`);
      assert.equal(directory.status(), 200);
      const companies = (await directory.json() as { items: { inn: string }[] }).items;
      assert.equal(companies.length, 2);
      await page.getByRole('button', { name: 'Материалы', exact: true }).click();
      const panel = page.getByRole('complementary', { name: 'Материалы проверки' });
      await panel.getByRole('textbox', { name: 'ИНН компаний' }).fill([...companies.map((company) => company.inn), '0000000000'].join('\n'));
      await panel.getByRole('button', { name: 'Добавить компании', exact: true }).click();
      await panel.getByRole('list', { name: 'Результат добавления' }).getByText('0000000000: нет в доступной базе', { exact: true }).waitFor();
      await page.reload();
      await panel.waitFor();
      const added = await context.request.get(`${run.baseURL}/api/v1/projects/${projectId}`);
      const created = await added.json() as { title: string; companies: unknown[]; context_version: number };
      assert.equal(created.title, renamed);
      assert.equal(created.companies.length, 2);
      assert.equal(created.context_version, 1);
      await Promise.all([
        page.waitForResponse((response) => response.request().method() === 'DELETE' && response.url().includes(`/projects/${projectId}/companies/`) && response.status() === 200),
        panel.getByRole('button', { name: 'Удалить', exact: true }).first().click(),
      ]);
      await page.reload();
      const removed = await context.request.get(`${run.baseURL}/api/v1/projects/${projectId}`);
      const final = await removed.json() as { companies: unknown[]; context_version: number };
      assert.equal(final.companies.length, 1);
      assert.equal(final.context_version, 2);
      await capture(run, page, viewport, 'live-rest', 'crud-reloaded');
      check(run, viewport, 'live-rest', 'Create/rename/add two/partial not_found/remove/reload', true, `project_id=${projectId}; no fixture interception`);
    });
  } finally { await context.close(); }
}


/** Capture the accepted HTML unchanged, in its own browser context and runtime. */
export async function runReference(run: Run, file: string) {
  for (const viewport of viewports) {
    const { context, page } = await makePage(run, viewport);
    page.setDefaultTimeout(30000);
    try {
      await caseRun(run, viewport, 'design-reference', 'Reference HTML renders S1/S2', async () => {
        await page.goto(pathToFileURL(file).href);
        await page.getByRole('heading', { name: 'Проверка контрагентов', exact: true }).waitFor();
        await capture(run, page, viewport, 'design-reference', 's1-populated');
        await page.getByRole('button', { name: /^Поставка оборудования к 20 сентября/ }).click();
        await page.getByRole('button', { name: 'Материалы', exact: true }).waitFor();
        await capture(run, page, viewport, 'design-reference', 's2-conversation');
        if (viewport.name !== 'tablet') {
          await page.getByRole('button', { name: 'Материалы', exact: true }).click();
          await capture(run, page, viewport, 'design-reference', 'materials');
        }
        check(run, viewport, 'design-reference', 'Unchanged reference captured', true);
      });
    } finally { await context.close(); }
  }
}
