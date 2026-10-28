import { useCallback, useEffect, useRef, useState } from 'react';

export const messageOf = (error: unknown) => error instanceof Error ? error.message : 'Не удалось выполнить действие.';

export function useResource<T>(loader: () => Promise<T>, interval = 15000) {
  const [dataState, setData] = useState<{ key: typeof loader; value: T }>();
  const [errorState, setError] = useState<{ key: typeof loader; value: string }>();
  const [loadingState, setLoading] = useState<{ key: typeof loader; value: boolean }>();
  const generation = useRef(0);
  const inFlight = useRef(false);
  const pending = useRef(false);
  const latestLoader = useRef(loader);
  latestLoader.current = loader;
  const refresh = useCallback(async () => {
    const current = ++generation.current;
    if (inFlight.current) { pending.current = true; return; }
    inFlight.current = true;
    const load = async (requestGeneration: number): Promise<void> => {
      const requestLoader = latestLoader.current;
      setLoading({ key: requestLoader, value: true });
      try {
        const result = await requestLoader();
        if (requestGeneration === generation.current && requestLoader === latestLoader.current) {
          setData({ key: requestLoader, value: result });
          setError({ key: requestLoader, value: '' });
        }
      } catch (failure) {
        if (requestGeneration === generation.current && requestLoader === latestLoader.current) {
          setError({ key: requestLoader, value: messageOf(failure) });
        }
      } finally {
        if (requestLoader !== latestLoader.current) return;
        if (pending.current) {
          pending.current = false;
          await load(generation.current);
        } else {
          inFlight.current = false;
          if (requestGeneration === generation.current && requestLoader === latestLoader.current) {
            setLoading({ key: requestLoader, value: false });
          }
        }
      }
    };
    await load(current);
  }, []);
  const poll = useCallback(() => {
    if (!inFlight.current) void refresh();
  }, [refresh]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (!document.hidden) poll(); }, interval);
    return () => {
      clearInterval(timer);
      generation.current++;
      if (latestLoader.current !== loader) { inFlight.current = false; pending.current = false; }
    };
  }, [loader, refresh, poll, interval]);
  return {
    data: dataState?.key === loader ? dataState.value : undefined,
    error: errorState?.key === loader ? errorState.value : '',
    loading: loadingState?.key === loader ? loadingState.value : true,
    refresh,
  };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const running = useRef(false);
  const run = async (action: () => Promise<unknown>) => {
    if (running.current) return false;
    running.current = true;
    setBusy(true);
    setError('');
    try { await action(); return true; }
    catch (failure) { setError(messageOf(failure)); return false; }
    finally { running.current = false; setBusy(false); }
  };
  return { busy, error, run };
}
