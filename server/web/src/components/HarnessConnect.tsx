import { useEffect, useState } from 'react';
import type { InitToken } from '../api/types';
import { initCommand, projectsApi } from '../api/projects';
import { useAction } from '../api/hooks';
import { dateTime, ErrorNotice } from './Common';

function Copy({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  const action = useAction();
  return <div className="space-y-2"><pre>{value}</pre><button className="secondary" onClick={() => {
    void action.run(async () => { await navigator.clipboard.writeText(value); setCopied(true); });
  }}>{copied ? 'Скопировано' : 'Копировать'}</button><ErrorNotice message={action.error} /></div>;
}

export function HarnessConnect({ projectId }: { projectId: string }) {
  const [token, setToken] = useState<InitToken>();
  const action = useAction();
  useEffect(() => {
    if (!token) return;
    const timer = window.setTimeout(() => setToken(undefined), Math.max(0, Date.parse(token.expires_at) - Date.now()));
    return () => clearTimeout(timer);
  }, [token]);
  return <section className="card">
    <h2>Подключение Harness</h2>
    <p className="muted">Одноразовый код действует 10 минут. Запустите команду в каталоге репозитория и введите код по запросу.</p>
    <ErrorNotice message={action.error} />
    <button disabled={action.busy} onClick={() => {
      void action.run(async () => { setToken(await projectsApi.init(projectId)); });
    }}>{action.busy ? 'Создание кода…' : 'Подключить Harness'}</button>
    {token && <div className="space-y-4">
      <div><h3>Init-код</h3><Copy key={token.code} value={token.code} /><p className="muted">До {dateTime(token.expires_at)}</p></div>
      <div><h3>Команда</h3><Copy value={initCommand(projectId)} /></div>
      <button className="secondary" onClick={() => setToken(undefined)}>Скрыть код</button>
    </div>}
  </section>;
}
