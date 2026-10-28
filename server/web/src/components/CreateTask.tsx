import { useState } from 'react';
import { useAction } from '../api/hooks';
import { projectsApi } from '../api/projects';
import { ErrorNotice } from './Common';

export function CreateTask({ projectId, onSaved }: { projectId: string; onSaved: () => Promise<void> }) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const action = useAction();
  return <details className="card"><summary className="cursor-pointer font-semibold">Создать задачу</summary>
    <ErrorNotice message={action.error} />
    <form onSubmit={async event => {
      event.preventDefault();
      await action.run(async () => {
        await projectsApi.createTask(projectId, title.trim(), description);
        setTitle(''); setDescription(''); await onSaved();
      });
    }}><fieldset disabled={action.busy}>
      <label>Название задачи<input required maxLength={200} pattern=".*\S.*" value={title} onChange={e => setTitle(e.target.value)} /></label>
      <label>Описание задачи<textarea aria-label="Описание задачи" required value={description} onChange={e => setDescription(e.target.value)} /></label>
      <button type="submit">Создать задачу</button>
    </fieldset></form>
  </details>;
}
