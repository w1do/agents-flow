import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { listAll, login, request, session } from './client';
import { tasksApi } from './tasks';
import { loadAgentCards, skillsApi } from './skills';
import { task } from '../test/fixtures';

const fetchMock = vi.fn();
const redirect = vi.fn();
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});

beforeEach(() => {
  session.clear();
  vi.stubGlobal('window', { location: { replace: redirect } });
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset(); redirect.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe('API transport', () => {
  it('rejects a VITE_API_BASE with a different origin during initialization', async () => {
    vi.stubGlobal('window', { location: { origin: 'https://panel.example.test', replace: redirect } });
    vi.stubEnv('VITE_API_BASE', 'https://api.example.test');
    vi.resetModules();
    await expect(import('./client')).rejects.toThrow(/VITE_API_BASE origin.*same origin/i);
  });
  it.each([
    ['', ''],
    ['https://panel.example.test/api', 'https://panel.example.test/api'],
    ['/gateway', '/gateway'],
  ])('accepts same-origin or empty VITE_API_BASE: %s', async (configured, expected) => {
    vi.stubGlobal('window', { location: { origin: 'https://panel.example.test', replace: redirect } });
    vi.stubEnv('VITE_API_BASE', configured);
    vi.resetModules();
    const client = await import('./client');
    expect(client.apiBase).toBe(expected);
  });
  it('uses cookie credentials and never stores the login JWT', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 })).mockResolvedValueOnce(json([]));
    await login('admin@example.test', 'password');
    await request('/projects');
    expect(session.authenticated()).toBe(true);
    expect(fetchMock.mock.calls[0][1].credentials).toBe('same-origin');
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBeUndefined();
    expect(fetchMock.mock.calls[0][1].headers['X-Requested-With']).toBe('XMLHttpRequest');
  });
  it('clears an expired session and redirects to login on 401', async () => {
    session.save(); fetchMock.mockResolvedValue(json({}, 401));
    await expect(request('/projects')).rejects.toThrow('Сессия истекла');
    expect(session.authenticated()).toBe(false); expect(redirect).toHaveBeenCalledWith('/login');
  });
  it('does not reload the login page after its cookie check returns 401', async () => {
    vi.stubGlobal('window', { location: { pathname: '/login', replace: redirect } });
    fetchMock.mockResolvedValue(json({}, 401));
    await expect(request('/auth/session')).rejects.toThrow('Сессия истекла');
    expect(redirect).not.toHaveBeenCalled();
  });
  it('keeps bad credentials on the login screen with a readable error', async () => {
    fetchMock.mockResolvedValue(json({}, 401));
    await expect(login('admin@example.test', 'wrong')).rejects.toThrow('неверные email');
    expect(redirect).not.toHaveBeenCalled();
  });
  it('loads every page of a list', async () => {
    fetchMock.mockResolvedValueOnce(json(Array.from({ length: 200 }, (_, id) => ({ id }))))
      .mockResolvedValueOnce(json([{ id: 200 }]));
    expect(await listAll('/projects')).toHaveLength(201);
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/projects?offset=200&limit=200');
  });
  it('uses contract bodies and unique idempotency keys for decisions and skill writes', async () => {
    fetchMock.mockResolvedValueOnce(json({})).mockResolvedValueOnce(json({}));
    await tasksApi.result('task-id', 'rework', 'Add coverage');
    await skillsApi.assign('agent-id', ['skill-id'], ['skill-id']);
    const first = fetchMock.mock.calls[0]; const second = fetchMock.mock.calls[1];
    expect(first[0]).toBe('/api/v1/tasks/task-id/result/decision');
    expect(JSON.parse(first[1].body)).toEqual({ decision: 'rework', feedback: 'Add coverage' });
    expect(second[1].method).toBe('PUT');
    expect(JSON.parse(second[1].body)).toEqual({ skill_ids: ['skill-id'], disabled_skill_ids: ['skill-id'] });
    expect(first[1].headers['Idempotency-Key']).toMatch(/^[a-f0-9-]{36}$/);
    expect(first[1].headers['Idempotency-Key']).not.toBe(second[1].headers['Idempotency-Key']);
  });
  it('does not expose validation input in an error', async () => {
    fetchMock.mockResolvedValue(json({ detail: [{ input: 'private value', msg: 'invalid' }] }, 422));
    await expect(request('/projects')).rejects.toThrow('Проверьте заполненные поля.');
  });
  it('raises an API error when a successful response body cannot be read', async () => {
    const unreadable = new Response(new ReadableStream({ start(controller) { controller.error(new Error('connection reset')); } }));
    fetchMock.mockResolvedValue(unreadable);
    await expect(request('/projects')).rejects.toThrow('Не удалось прочитать ответ сервера.');
  });
  it('keeps the current task snapshot visible while publication is pending', async () => {
    fetchMock.mockResolvedValue(json([]));
    const [agent] = await loadAgentCards([{
      id: 'agent-id', project_id: 'project-id', name: 'Worker', status: 'busy',
      last_heartbeat_at: null, git_remote: '', repository_path_hint: '',
    }], [
      { ...task, status: 'merged', assigned_agent_id: 'agent-id' },
      { ...task, id: 'completed', status: 'merged', assigned_agent_id: 'agent-id', completed_at: '2026-10-27T00:00:00Z' },
    ]);
    expect(agent.tasks.map(task => task.id)).toEqual(['task-id']);
  });
});
