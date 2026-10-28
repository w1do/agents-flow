import { useSkillForm } from '../api/forms';
import type { Category, Skill } from '../api/types';
import { ErrorNotice } from './Common';

const MAX_MARKDOWN_BYTES = 256 * 1024;

export function SkillForm({ skill, categories, onSaved, onCancel }: {
  skill?: Skill; categories: Category[]; onSaved: () => Promise<void>; onCancel: () => void;
}) {
  const form = useSkillForm(skill, categories, onSaved);
  const contentBytes = new TextEncoder().encode(form.content).byteLength;
  const contentTooLarge = contentBytes > MAX_MARKDOWN_BYTES;
  return <section className="card">
    <h2>{skill ? `Правка: ${skill.name}` : 'Новый skill'}</h2>
    <ErrorNotice message={form.action.error} />
    {form.saved && <p role="status" className="text-sm text-emerald-700">Сохранено. Версия и хеш обновлены в карточке.</p>}
    {form.warnings.length > 0 && <p role="status" className="text-sm text-amber-800">Предупреждения API: {form.warnings.join(', ')}</p>}
    <form onSubmit={form.submit} onChange={() => form.setSaved(false)}><fieldset disabled={form.action.busy}>
      <label>Категория<select aria-label="Категория" required value={form.categoryId} onChange={e => form.setCategoryId(e.target.value)}>
        <option value="" disabled>Выберите категорию</option>
        {categories.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}
      </select></label>
      <label>Название skill<input required maxLength={200} pattern=".*\S.*" value={form.name} onChange={e => form.setName(e.target.value)} /></label>
      <label>Описание skill<textarea aria-label="Описание skill" value={form.description} onChange={e => form.setDescription(e.target.value)} /></label>
      <label>Markdown<textarea aria-label="Markdown" className="min-h-64 font-mono" required value={form.content} onChange={e => form.setContent(e.target.value)} /></label>
      <p className={contentTooLarge ? 'text-sm text-red-700' : 'muted'} role={contentTooLarge ? 'alert' : undefined}>
        {contentTooLarge ? 'Markdown превышает лимит 256 КиБ в UTF-8.' : `Размер Markdown: ${contentBytes} / ${MAX_MARKDOWN_BYTES} байт.`}
      </p>
      <div className="actions"><button type="submit" disabled={contentTooLarge}>Сохранить skill</button><button type="button" className="secondary" onClick={onCancel}>Закрыть</button></div>
      <p className="muted">Версия растёт при изменении Markdown.</p>
    </fieldset></form>
  </section>;
}
