// @vitest-environment jsdom
import { expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { session } from '../api/client';
import { App } from '../App';
import { Skills } from '../pages/Skills';
import { TaskDecisions } from '../components/TaskDecisions';
import { category, skill, task } from './fixtures';
import { fetchMock, json } from './helpers';

it.each([
  ['backlog', 'Утвердить план', 'plan', 'approved'], ['backlog', 'Доработать план', 'plan', 'rejected'],
  ['backlog', 'Отклонить план', 'plan', 'trash'], ['ready', 'Принять и опубликовать', 'result', 'publish'],
  ['ready', 'Доработать результат', 'result', 'rework'], ['ready', 'Оставить ready', 'result', 'keep_ready'],
] as const)('sends %s decision: %s', async (status, label, kind, decision) => {
  fetchMock.mockResolvedValue(json({ ...task, status }));
  const saved = vi.fn().mockResolvedValue(undefined); const user = userEvent.setup();
  render(<MemoryRouter><TaskDecisions task={{ ...task, status }} onSaved={saved} /></MemoryRouter>);
  const button = screen.getByRole('button', { name: label }) as HTMLButtonElement;
  if (['rejected', 'rework'].includes(decision)) expect(button.disabled).toBe(true);
  await user.type(screen.getByLabelText('Замечания'), 'Review feedback'); await user.click(button);
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(fetchMock.mock.calls[0][0]).toBe(`/api/v1/tasks/task-id/${kind}/decision`);
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ decision, feedback: 'Review feedback' });
});

it('creates a Harness connection code for a project', async () => {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith('/init-tokens')) return json({ code: 'one-time-code', expires_at: new Date(Date.now() + 60000).toISOString() }, 201);
    if (url.includes('/tasks') || url.includes('/agents')) return json([]);
    if (url.endsWith('/projects/project-id')) return json({ id: 'project-id', name: 'Demo', description: '', agents: [] });
    return json([]);
  });
  session.save(); const user = userEvent.setup();
  render(<MemoryRouter initialEntries={['/projects/project-id']}><App /></MemoryRouter>);
  expect(await screen.findByRole('heading', { name: 'Demo' })).toBeTruthy();
  expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/projects/project-id')).toBe(true);
  await user.click(screen.getByRole('button', { name: 'Подключить Harness' }));
  expect(await screen.findByText('one-time-code')).toBeTruthy();
});

it('loads skills and renders the saved version and hash', async () => {
  let updated = false;
  fetchMock.mockImplementation(async (url: string) => {
    if (url.endsWith('/skill-categories?offset=0&limit=200')) return json([category]);
    if (url.endsWith('/skills?offset=0&limit=200')) return json([updated ? { ...skill, content: '# Updated', version: 2, content_hash: 'hash-v2' } : skill]);
    if (url.endsWith('/skills/skill-id')) { updated = true; return json({ ...skill, content: '# Updated', version: 2, content_hash: 'hash-v2' }); }
    return json([]);
  });
  session.save(); const user = userEvent.setup(); render(<MemoryRouter><Skills /></MemoryRouter>);
  await screen.findByText('Testing · v1');
  expect(fetchMock.mock.calls.some(([url]) => url === '/api/v1/skills?offset=0&limit=200')).toBe(true);
  await user.click(screen.getByRole('button', { name: 'Править' }));
  await user.clear(screen.getByRole('textbox', { name: 'Markdown' }));
  await user.type(screen.getByRole('textbox', { name: 'Markdown' }), '# Updated');
  await user.click(screen.getByRole('button', { name: 'Сохранить skill' }));
  expect(await screen.findByText('Testing · v2')).toBeTruthy(); expect(screen.getByText('hash-v2')).toBeTruthy();
});

it('limits Markdown by UTF-8 bytes', async () => {
  fetchMock.mockImplementation(async (url: string) => url.includes('skill-categories') ? json([category]) : json([]));
  session.save(); render(<MemoryRouter><Skills /></MemoryRouter>);
  await screen.findByRole('button', { name: 'Создать skill' });
  await userEvent.setup().click(screen.getByRole('button', { name: 'Создать skill' }));
  const editor = screen.getByRole('textbox', { name: 'Markdown' });
  fireEvent.change(editor, { target: { value: 'я'.repeat(200_000) } });
  expect(screen.getByRole('alert').textContent).toContain('256 КиБ в UTF-8');
  expect((screen.getByRole('button', { name: 'Сохранить skill' }) as HTMLButtonElement).disabled).toBe(true);
});

it('assigns skills through the catalog', async () => {
  fetchMock.mockImplementation(async (url: string, init: RequestInit) => {
    if (url.endsWith('/skill-categories?offset=0&limit=200')) return json([category]);
    if (url.endsWith('/skills?offset=0&limit=200')) return json([skill]);
    if (url.endsWith('/projects?offset=0&limit=200')) return json([{ id: 'project-id', name: 'Demo' }]);
    if (url.endsWith('/projects/project-id/agents?offset=0&limit=200')) return json([{ id: 'agent-id', project_id: 'project-id', name: 'Agent', status: 'idle' }]);
    if (url.endsWith('/agents/agent-id/skills')) return json(init.method === 'PUT' ? [skill] : []);
    return json([]);
  });
  session.save(); const user = userEvent.setup(); render(<MemoryRouter><Skills /></MemoryRouter>);
  await screen.findByText('Набор skills: Agent'); await user.click(screen.getByRole('checkbox', { name: /Testing/ }));
  await user.click(screen.getByRole('button', { name: 'Сохранить назначения' }));
  expect(await screen.findByText('Назначения сохранены')).toBeTruthy();
  const call = fetchMock.mock.calls.find(([url, init]) => url.endsWith('/agents/agent-id/skills') && init.method === 'PUT');
  expect(JSON.parse(call![1].body)).toEqual({ skill_ids: ['skill-id'], disabled_skill_ids: [] });
});
