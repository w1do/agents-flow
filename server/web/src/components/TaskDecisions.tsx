import { useState } from 'react';
import { useAction } from '../api/hooks';
import { tasksApi } from '../api/tasks';
import type { PlanDecision, ResultDecision, Task } from '../api/types';
import { ErrorNotice } from './Common';

export function TaskDecisions({ task, onSaved }: { task: Task; onSaved: () => Promise<void> }) {
  const [feedback, setFeedback] = useState('');
  const action = useAction();
  const decide = (kind: 'plan' | 'result', decision: PlanDecision | ResultDecision) => {
    void action.run(async () => {
      if (kind === 'plan') await tasksApi.plan(task.id, decision as PlanDecision, feedback.trim());
      else await tasksApi.result(task.id, decision as ResultDecision, feedback.trim());
      setFeedback(''); await onSaved();
    });
  };
  const changeStatus = (status: 'new' | 'paused' | 'trash') => {
    void action.run(async () => { await tasksApi.status(task.id, status); await onSaved(); });
  };
  const canPause = ['new', 'choosing', 'planning', 'backlog', 'active', 'testing', 'ready'].includes(task.status);
  return <section className="card"><h2>Решение администратора</h2>
    <ErrorNotice message={action.error} />
    <fieldset disabled={action.busy}>
      {['backlog', 'ready'].includes(task.status) && <label>Замечания
        <textarea aria-label="Замечания" value={feedback} onChange={e => setFeedback(e.target.value)} placeholder="Обязательны для доработки" />
      </label>}
      {task.status === 'backlog' && <div className="actions">
        <button onClick={() => decide('plan', 'approved')}>Утвердить план</button>
        <button className="secondary" disabled={!feedback.trim()} onClick={() => decide('plan', 'rejected')}>Доработать план</button>
        <button className="danger" onClick={() => decide('plan', 'trash')}>Отклонить план</button>
      </div>}
      {task.status === 'ready' && <div className="actions">
        <button onClick={() => decide('result', 'publish')}>Принять и опубликовать</button>
        <button className="secondary" disabled={!feedback.trim()} onClick={() => decide('result', 'rework')}>Доработать результат</button>
        <button className="secondary" onClick={() => decide('result', 'keep_ready')}>Оставить ready</button>
      </div>}
      <div className="actions">
        {canPause && <button className="secondary" onClick={() => changeStatus('paused')}>Приостановить</button>}
        {task.status === 'stalled' && <button onClick={() => changeStatus('new')}>Вернуть в очередь</button>}
        {task.status !== 'trash' && <button className="danger" onClick={() => changeStatus('trash')}>В корзину</button>}
      </div>
      {!['backlog', 'ready'].includes(task.status) && <p className="muted">Приёмка доступна в backlog (план) и ready (результат).</p>}
    </fieldset>
  </section>;
}
