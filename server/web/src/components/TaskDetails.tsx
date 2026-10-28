import type { Task, TaskEvent } from '../api/types';
import { dateTime, JsonBlock, Section } from './Common';

function Events({ events }: { events: TaskEvent[] }) {
  return events.length ? <ol className="space-y-4">{events.map(event => <li key={event.id} className="space-y-2 border-l-2 border-slate-200 pl-4">
    <div className="toolbar"><strong className="text-sm">{event.event_type}</strong><time className="muted">{dateTime(event.created_at)}</time></div>
    <p className="whitespace-pre-wrap text-sm">{event.message}</p>
    {event.event_type === 'publication-result' && <p className={event.payload?.success ? 'text-emerald-700' : 'text-rose-700'}>
      {event.payload?.success ? 'Публикация выполнена' : 'Ошибка публикации'}
    </p>}
    {event.payload && <details><summary className="cursor-pointer text-sm text-indigo-700">Подробности события</summary><JsonBlock value={event.payload} /></details>}
  </li>)}</ol> : <p className="muted">Событий пока нет</p>;
}

export function TaskDetails({ task }: { task: Task }) {
  const errors = task.events.filter(event => ['error', 'fail', 'failed', 'stalled', 'lease_expired'].includes(event.event_type));
  const publication = task.events.filter(event => ['publication-result', 'result_decision'].includes(event.event_type));
  const tests = task.events.filter(event => event.event_type === 'test_result');
  return <>
    {['error', 'stalled'].includes(task.status) && <Section title="Ошибка и восстановление">
      <Events events={errors.length ? errors : task.events.slice(-5)} /><h3>Сохранённый checkpoint</h3><JsonBlock value={task.checkpoint} />
    </Section>}
    <div className="grid items-start gap-6 lg:grid-cols-2">
      <Section title={`План · версия ${task.plan_revision}`}>
        <p className="muted">Решение: {task.plan_decision}</p>
        <p className="whitespace-pre-wrap text-sm">{task.plan_text || 'План ещё не представлен'}</p>
        {task.plan_feedback && <p className="whitespace-pre-wrap text-sm">Замечания: {task.plan_feedback}</p>}
      </Section>
      <Section title="Отчёт и изменённые файлы">
        <p className="whitespace-pre-wrap text-sm">{task.result_summary || 'Отчёт ещё не представлен'}</p>
        <JsonBlock value={task.result_data} empty="Изменённые файлы и результаты появятся в отчёте агента" />
      </Section>
      <Section title="Тесты и проверки">
        <JsonBlock value={task.result_data?.tests} empty="Сводка тестов ещё не представлена" />
        <Events events={tests} />
      </Section>
      <Section title="Публикация">
        {task.status === 'merged' && !publication.some(event => event.event_type === 'publication-result') &&
          <p className="muted">Публикация разрешена. Ожидается результат Harness.</p>}
        <Events events={publication} />
      </Section>
    </div>
    <Section title="Skills задачи (снимок)">
      {task.skill_snapshots.map(skill => <div className="space-y-1 border-b pb-3 text-sm" key={skill.id}>
        <p>{skill.category} / {skill.skill_name} · v{skill.skill_version}{skill.content_missing ? ' · содержимое недоступно' : ''}</p>
        <p className="break-all font-mono text-xs text-slate-500">{skill.content_hash}</p>
      </div>)}
      {!task.skill_snapshots.length && <p className="muted">Снимок пуст</p>}
    </Section>
    <Section title="Лента событий и решений"><Events events={task.events} /></Section>
    <details className="card"><summary className="cursor-pointer font-semibold">Checkpoint</summary><JsonBlock value={task.checkpoint} /></details>
  </>;
}
