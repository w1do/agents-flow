// @vitest-environment jsdom
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useResource } from '../api/hooks';
import './helpers';

afterEach(() => vi.useRealTimers());

it('applies each response when consecutive polls take longer than the interval', async () => {
  const resolvers: Array<(value: string) => void> = [];
  const loader = vi.fn(() => new Promise<string>(resolve => resolvers.push(resolve)));
  function Probe() { const resource = useResource(loader, 100); return <p role="status">{resource.data ?? 'Загрузка'}</p>; }
  vi.useFakeTimers(); render(<Probe />);

  for (let version = 1; version <= 3; version++) {
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    expect(loader).toHaveBeenCalledTimes(version);
    await act(async () => { resolvers[version - 1](`v${version}`); });
    expect(screen.getByRole('status').textContent).toBe(`v${version}`);
  }
  expect(loader).toHaveBeenCalledTimes(3);
});

it('applies three consecutive slow refresh responses after saving', async () => {
  const resolvers: Array<(value: string) => void> = [];
  let calls = 0;
  const loader = vi.fn(() => calls++ === 0
    ? Promise.resolve('v1')
    : new Promise<string>(resolve => resolvers.push(resolve)));
  function Probe() {
    const resource = useResource(loader, 100);
    return <><button onClick={() => void resource.refresh()}>Сохранить</button><p role="status">{resource.data ?? 'Загрузка'}</p></>;
  }
  vi.useFakeTimers(); render(<Probe />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByRole('status').textContent).toBe('v1');
  fireEvent.click(screen.getByRole('button', { name: 'Сохранить' }));

  for (let version = 2; version <= 4; version++) {
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    expect(loader).toHaveBeenCalledTimes(version);
    await act(async () => { resolvers[version - 2](`v${version}`); });
    expect(screen.getByRole('status').textContent).toBe(`v${version}`);
  }
});
