import type { ReactNode } from 'react';

export function ErrorNotice({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{message}</p> : null;
}

export function Refresh({ loading, onClick }: { loading: boolean; onClick: () => unknown }) {
  return <button className="secondary" disabled={loading} onClick={() => { onClick(); }}>
    {loading ? 'Обновление…' : 'Обновить'}
  </button>;
}

export function Status({ value }: { value: string }) {
  const colors = ['error', 'stalled'].includes(value) ? 'bg-rose-100 text-rose-800'
    : ['ready', 'merged', 'idle'].includes(value) ? 'bg-emerald-100 text-emerald-800'
    : ['active', 'testing', 'busy'].includes(value) ? 'bg-indigo-100 text-indigo-800' : '';
  return <span className={`badge ${colors}`}>{value}</span>;
}

export function JsonBlock({ value, empty = 'Нет данных' }: { value: unknown; empty?: string }) {
  return value == null ? <p className="muted">{empty}</p> : <pre>{JSON.stringify(value, null, 2)}</pre>;
}

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="card"><h2>{title}</h2>{children}</section>;
}

export const dateTime = (value: string | null) => value ? new Date(value).toLocaleString('ru-RU') : 'Нет данных';
