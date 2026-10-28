import { useProjectForm } from '../api/forms';
import { ErrorNotice } from './Common';

export function CreateProject({ onSaved }: { onSaved: () => Promise<void> }) {
  const form = useProjectForm(onSaved);
  return <section className="card">
    <h2>Новый проект</h2><ErrorNotice message={form.action.error} />
    <form onSubmit={form.submit}><fieldset disabled={form.action.busy}>
      <label>Название<input required maxLength={200} pattern=".*\S.*" value={form.name} onChange={e => form.setName(e.target.value)} /></label>
      <label>Описание<textarea aria-label="Описание" value={form.description} onChange={e => form.setDescription(e.target.value)} /></label>
      <button type="submit">Создать проект</button>
    </fieldset></form>
  </section>;
}
