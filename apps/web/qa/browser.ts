import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout } from 'node:timers/promises';
import { chromium } from 'playwright-core';

/** Start Chrome with an isolated disposable profile; Playwright owns the CDP protocol. */
export async function startChrome(executablePath: string) {
  const profile = await mkdtemp(join(tmpdir(), 'counterparty-web07-'));
  const child = spawn(executablePath, [
    '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
  ], { stdio: 'ignore' });
  let startError: Error | undefined;
  child.on('error', (error) => { startError = error; });
  try {
    let endpoint: string | undefined;
    for (let attempt = 0; attempt < 200; attempt += 1) {
      if (startError) throw startError;
      if (child.exitCode !== null) throw new Error(`Chrome exited ${child.exitCode}`);
      try {
        const [port, path] = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).trim().split('\n');
        if (port && path) { endpoint = `http://127.0.0.1:${port}`; break; }
      } catch { /* Chrome has not written its debugging endpoint yet. */ }
      await setTimeout(50);
    }
    if (!endpoint) throw new Error('Chrome did not publish a CDP endpoint within 10s');
    const browser = await chromium.connectOverCDP(endpoint);
    return {
      browser,
      close: async () => {
        await browser.close();
        child.kill('SIGTERM');
        await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
      },
    };
  } catch (error) {
    child.kill('SIGTERM');
    await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
    throw error;
  }
}
