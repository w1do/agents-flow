import { useCategoryForm } from '../api/forms';
import { ErrorNotice } from './Common';

export function CategoryForm({ onSaved }: { onSaved: () => Promise<void> }) {
  const form = useCategoryForm(onSaved);
  return <details className="card"><summary className="cursor-pointer font-semibold">Новая категория</summary>
    <ErrorNotice message={form.action.error} />
    <form onSubmit={form.submit}><fieldset disabled={form.action.busy}>
      <label>Название категории<input required maxLength={200} pattern=".*\S.*" value={form.name} onChange={e => form.setName(e.target.value)} /></label>
      <label>Описание категории<textarea aria-label="Описание категории" value={form.description} onChange={e => form.setDescription(e.target.value)} /></label>
      <button type="submit">Создать категорию</button>
    </fieldset></form>
  </details>;
}
