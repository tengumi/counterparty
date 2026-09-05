import { afterEach, describe, expect, it, vi } from 'vitest';
import { addCompanies, createProject } from './client';
import { apiProjects } from '../test/setup';

afterEach(() => vi.restoreAllMocks());

describe('workspace REST client', () => {
  it.each([
    { status: 201, replay: null, expected: false },
    { status: 200, replay: 'true', expected: true },
  ])('distinguishes a $status create response from an idempotent replay', async ({ status, replay, expected }) => {
    const headers = replay ? { 'idempotent-replay': replay } : undefined;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(apiProjects[0], { status, headers })));

    const result = await createProject('Проверьте компанию', 'request-1');

    expect(result.replayed).toBe(expected);
    expect(result.project.id).toBe('demo-project');
    expect(fetch).toHaveBeenCalledWith('/api/v1/projects', expect.objectContaining({ credentials: 'include' }));
  });

  it.each([
    ['request_in_flight', true],
    ['request_id_reused', false],
  ])('preserves a 409 %s reason for the UI', async (reason, retryable) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
      code: 'conflict', message: 'conflict', retryable, request_id: 'server-request', details: { reason },
    }, { status: 409 })));

    const promise = createProject('Проверьте компанию', 'request-1');

    await expect(promise).rejects.toMatchObject({
      status: 409, code: 'conflict', retryable, details: { reason },
    });
  });

  it('keeps every per-item outcome from a partial add response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
      schema_version: '0.1', project_id: 'demo-project', companies: [], context_version: 1,
      results: [
        { requested: { inn: '7449088645' }, outcome: 'added', company_id: 'company-a', report_id: 'report-a', error_code: null, message: null },
        { requested: { inn: '0000000000' }, outcome: 'not_found', company_id: null, report_id: null, error_code: 'not_found', message: 'not held' },
      ],
    })));

    const result = await addCompanies('demo-project', ['7449088645', '0000000000'], 0);

    expect(result.results.map((item) => item.outcome)).toEqual(['added', 'not_found']);
    const request = vi.mocked(fetch).mock.calls[0]?.[1];
    expect(JSON.parse(String(request?.body))).toEqual({
      items: [{ inn: '7449088645' }, { inn: '0000000000' }], expected_context_version: 0,
    });
  });

  it('surfaces a 21-company limit refusal instead of treating it as an empty result', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({
      code: 'limit_exceeded', message: 'too many', retryable: false, request_id: 'server-request',
      details: { limit: 20, in_project: 20, requested_new: 1 },
    }, { status: 409 })));

    await expect(addCompanies('demo-project', ['7700000021'], 1)).rejects.toMatchObject({
      status: 409, code: 'limit_exceeded', details: { limit: 20, in_project: 20, requested_new: 1 },
    });
  });

  it('turns a network failure into an explicit unavailable error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));

    await expect(createProject('Проверьте компанию', 'request-1')).rejects.toMatchObject({
      status: 0, code: 'network_error', retryable: true,
    });
  });
});
