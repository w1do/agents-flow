// @vitest-environment jsdom
import { StrictMode } from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { useResource } from '../api/hooks';
import { Task } from '../pages/Task';
import { task } from './fixtures';
import { fetchMock, json } from './helpers';

it('repeats a refresh requested while a request is in flight', async () => {
  let resolve!: (value: string) => void;
  let calls = 0;
  const loader = vi.fn(() => calls++ === 0
    ? new Promise<string>(done => { resolve = done; })
    : Promise.resolve('Актуальные данные'));
  function Probe() { const resource = useResource(loader); return <><button onClick={() => void resource.refresh()}>Обновить</button><p role="status">{resource.data ?? 'Загрузка'}</p></>; }
  render(<Probe />);
  await waitFor(() => expect(loader).toHaveBeenCalledOnce());
  await act(async () => { screen.getByRole('button', { name: 'Обновить' }).click(); });
  expect(loader).toHaveBeenCalledOnce();
  await act(async () => { resolve('Устаревшие данные'); });
  expect(await screen.findByText('Актуальные данные')).toBeTruthy();
  expect(loader).toHaveBeenCalledTimes(2);
});

it('uses the latest loader after a refresh is queued', async () => {
  let resolve!: (value: string) => void;
  const first = vi.fn(() => new Promise<string>(done => { resolve = done; }));
  const second = vi.fn(async () => 'Новый loader');
  function Probe({ loader }: { loader: () => Promise<string> }) { const resource = useResource(loader); return <><button onClick={() => void resource.refresh()}>Обновить</button><p role="status">{resource.data ?? 'Загрузка'}</p></>; }
  const view = render(<Probe loader={first} />);
  await waitFor(() => expect(first).toHaveBeenCalledOnce());
  await act(async () => { screen.getByRole('button', { name: 'Обновить' }).click(); });
  view.rerender(<Probe loader={second} />);
  await act(async () => { resolve('Старый loader'); });
  expect(await screen.findByText('Новый loader')).toBeTruthy();
  expect(second).toHaveBeenCalledOnce();
});

it('finishes the first load when StrictMode replays mount effects', async () => {
  const resolvers: Array<(value: string) => void> = [];
  const loader = vi.fn(() => new Promise<string>(done => { resolvers.push(done); }));
  function Probe() { const resource = useResource(loader); return <p role="status">{resource.loading ? 'Загрузка' : resource.data}</p>; }
  render(<StrictMode><Probe /></StrictMode>);
  await waitFor(() => expect(loader).toHaveBeenCalledOnce());
  await act(async () => { resolvers[0]('Старый запрос'); await Promise.resolve(); });
  await act(async () => { resolvers[1]('Загрузка завершена'); });
  expect(await screen.findByText('Загрузка завершена')).toBeTruthy();
  expect(loader).toHaveBeenCalledTimes(2);
});

it('loads the new task after a route change and only publishes the current task', async () => {
  let resolveA!: (response: Response) => void;
  fetchMock.mockImplementation((url: string, init: RequestInit) => {
    if (url === '/api/v1/tasks/a') return new Promise<Response>(resolve => { resolveA = resolve; });
    if (url === '/api/v1/tasks/b') return Promise.resolve(json({ ...task, id: 'b', title: 'Задача B' }));
    if (init.method === 'POST') return Promise.resolve(json({ ...task, id: 'b', title: 'Задача B' }));
    return Promise.resolve(json({}));
  });
  const user = userEvent.setup();
  render(<MemoryRouter initialEntries={['/tasks/a']}>
    <Link to="/tasks/b">Открыть B</Link>
    <Routes><Route path="/tasks/:id" element={<Task />} /></Routes>
  </MemoryRouter>);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/v1/tasks/a', expect.anything()));
  await user.click(screen.getByRole('link', { name: 'Открыть B' }));
  expect(await screen.findByRole('heading', { name: 'Задача B' })).toBeTruthy();
  await act(async () => { resolveA(json({ ...task, id: 'a', title: 'Устаревшая задача A' })); });
  expect(screen.queryByRole('heading', { name: 'Устаревшая задача A' })).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Принять и опубликовать' }));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/tasks/b/result/decision' && init.method === 'POST')).toBe(true));
  expect(fetchMock.mock.calls.some(([url, init]) => url === '/api/v1/tasks/a/result/decision' && init.method === 'POST')).toBe(false);
});
