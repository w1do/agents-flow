// @vitest-environment jsdom
import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { App } from '../App';
import { session } from '../api/client';
import { fetchMock, json } from './helpers';

it('protects direct task links without making data requests', async () => {
  fetchMock.mockResolvedValue(json({}, 401));
  render(<MemoryRouter initialEntries={['/tasks/task-id']}><App /></MemoryRouter>);
  expect(await screen.findByRole('heading', { name: 'Вход в панель' })).toBeTruthy();
  expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/auth/session');
});

it('logs in and creates a project without manual reload', async () => {
  let created = false;
  fetchMock.mockImplementation(async (_url: string, init: RequestInit) => {
    if (_url.endsWith('/auth/session')) return json({}, 401);
    if (_url.endsWith('/auth/login')) return new Response(null, { status: 204 });
    if (init.method === 'POST') { created = true; return json({}, 201); }
    return json(created ? [{ id: 'project-id', name: 'Demo', agents: [], active_task_count: 0 }] : []);
  });
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={['/login']}><App /></MemoryRouter>);
  await user.type(await screen.findByLabelText('Email'), 'admin@example.test');
  await user.type(screen.getByLabelText('Пароль'), 'password');
  await user.click(screen.getByRole('button', { name: 'Войти' }));
  await screen.findByRole('heading', { name: 'Проекты' });
  await user.type(screen.getByLabelText('Название'), 'Demo');
  await user.click(screen.getByRole('button', { name: 'Создать проект' }));
  expect(await screen.findByRole('link', { name: 'Demo' })).toBeTruthy();
  expect(session.authenticated()).toBe(true);
});
