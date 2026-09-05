import type { Page, Route } from 'playwright-core';
import type { ApiProject } from '../src/api/contracts.ts';
import { apiProjects } from '../src/test/apiProjects.ts';

export type ListState = 'populated' | 'empty' | 'loading' | 'error';

/** Browser-only REST interception; the application still uses its normal fetch client. */
export async function installFixtures(page: Page) {
  const projects: ApiProject[] = structuredClone([...apiProjects]);
  const requests: string[] = [];
  const pending: Route[] = [];
  const state = { list: 'populated' as ListState, submitFails: false, detailFails: false };
  const failure = {
    code: 'dependency_unavailable', message: 'Synthetic WEB-07 service failure',
    retryable: true, request_id: 'web07-fixture', details: null,
  };
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    requests.push(`${method} ${path}`);
    if (path === '/api/v1/projects' && method === 'GET') {
      if (state.list === 'loading') { pending.push(route); return; }
      if (state.list === 'error') { await route.fulfill({ status: 503, json: failure }); return; }
      await route.fulfill({ json: {
        schema_version: '0.1', items: state.list === 'empty' ? [] : projects,
        page: { limit: 100, next_cursor: null, has_more: false },
      } });
      return;
    }
    if (path === '/api/v1/projects' && method === 'POST') {
      await route.fulfill(state.submitFails ? { status: 503, json: failure } : { status: 201, json: projects[0] });
      return;
    }
    const match = path.match(/^\/api\/v1\/projects\/([^/]+)$/);
    const index = projects.findIndex((project) => project.id === match?.[1]);
    if (match && index >= 0) {
      if (state.detailFails) { await route.fulfill({ status: 503, json: failure }); return; }
      if (method === 'PATCH') {
        const body = request.postDataJSON() as { title: string };
        projects[index] = { ...projects[index]!, title: body.title };
      }
      await route.fulfill({ json: projects[index] });
      return;
    }
    await route.fulfill({ status: 404, json: { ...failure, code: 'not_found', retryable: false } });
  });
  // No model/provider is contacted by visual fixtures. Sending a real run belongs to WEB-09.
  await page.route('**/rpc/agent/**', (route) => route.fulfill({ status: 503, json: failure }));
  return {
    state, projects, requests,
    release: async () => { await Promise.all(pending.splice(0).map((route) => route.abort().catch(() => undefined))); },
  };
}
