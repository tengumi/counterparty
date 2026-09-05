import { execFileSync } from 'node:child_process';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve } from 'node:path';
import { startChrome } from './browser.ts';
import { matrix } from './config.ts';
import type { Manifest } from './config.ts';
import { runFixtures, runLive, runReference } from './scenarios.ts';

const args = process.argv.slice(2);
const option = (name: string, fallback: string) => args.find((arg) => arg.startsWith(`${name}=`))?.slice(name.length + 1) ?? fallback;
const mode = option('--mode', 'fixtures');
if (!['fixtures', 'live', 'all'].includes(mode)) throw new Error('--mode must be fixtures, live or all');
if (!args.includes('--capture')) {
  console.log(JSON.stringify({ mode, matrix, browserStarted: false, next: 'npm run qa:browser -- --capture --mode=all' }, null, 2));
} else {
  const baseURL = option('--url', 'http://127.0.0.1:5173');
  const output = resolve(option('--output', '../../artifacts/qa/WEB-07'));
  const executable = option('--chrome', process.env.WEB07_CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome');
  const sourceSHA = execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  const sourceDirty = execFileSync('git', ['status', '--porcelain', '--', '.', ':!../../artifacts/qa/WEB-07'], { encoding: 'utf8' }).trim().length > 0;
  if (sourceDirty) throw new Error('Commit the reviewed source before capture: manifest must identify a clean source SHA');
  await mkdir(output, { recursive: true });
  const referenceFile = resolve('../../artifacts/Design TZ для экранов/Проверка контрагентов v2.dc.html');
  const digest = async (path: string) => createHash('sha256').update(await readFile(path)).digest('hex');
  const reference = { file: 'artifacts/Design TZ для экранов/Проверка контрагентов v2.dc.html', sha256: await digest(referenceFile), supportSHA256: await digest(resolve('../../artifacts/Design TZ для экранов/support.js')) };
  const chrome = await startChrome(executable);
  const manifest: Manifest = {
    scope: 'WEB-07', sourceSHA, sourceDirty, createdAt: new Date().toISOString(),
    browser: chrome.browser.version(), transport: 'Playwright connectOverCDP', baseURL,
    reference, checks: [], captures: [], consoleErrors: [],
    limitations: [
      'Typed fixture screenshots verify WEB-07 presentation only; report/materials/conversation data remains mock and does not close WEB-08/09.',
      'Text zoom check doubles computed font sizes to emulate 200% text-only zoom; OS virtual keyboard and native Chrome zoom are not emulated.',
      'Design reference is the unchanged HTML with its own support.js and pinned unpkg CDN dependencies; its narrow-screen shell differs from Specs 07 responsive requirements.',
      'Document source screen is the existing honest preview placeholder, not document reading acceptance.',
      'Live CRUD uses real REST and server-generated UUIDs in a disposable demo database; it does not validate live report/agent screens.',
    ],
  };
  try {
    const run = { browser: chrome.browser, manifest, output, baseURL };
    if (mode !== 'live') { await runReference(run, referenceFile); await runFixtures(run); }
    if (mode !== 'fixtures') await runLive(run);
  } finally {
    await writeFile(resolve(output, `manifest-${mode}.json`), `${JSON.stringify(manifest, null, 2)}\n`);
    await chrome.close();
  }
  const failed = manifest.checks.filter((check) => check.verdict === 'fail');
  console.log(JSON.stringify({ sourceSHA, captures: manifest.captures.length, checks: manifest.checks.length, failed, consoleErrors: manifest.consoleErrors, output }, null, 2));
  if (failed.length || manifest.consoleErrors.length) process.exitCode = 1;
}
