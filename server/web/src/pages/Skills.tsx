import { useState } from 'react';
import { useResource } from '../api/hooks';
import { skillsApi } from '../api/skills';
import type { Skill } from '../api/types';
import { AgentAssignment } from '../components/AgentAssignment';
import { CategoryForm } from '../components/CategoryForm';
import { ErrorNotice, Refresh } from '../components/Common';
import { SkillCard } from '../components/SkillCard';
import { SkillForm } from '../components/SkillForm';

export function Skills() {
  const resource = useResource(skillsApi.catalog);
  const [categoryId, setCategoryId] = useState('');
  const [editor, setEditor] = useState<Skill | 'new' | null>(null);
  const data = resource.data;
  const filtered = data?.skills.filter(skill => !categoryId || skill.category_id === categoryId);
  return <>
    <div className="toolbar"><div><h1>Skills</h1><p className="muted">Каталог инструкций и назначения агентам.</p></div>
      <Refresh loading={resource.loading} onClick={resource.refresh} /></div>
    <ErrorNotice message={resource.error} />
    {!data && resource.loading && <p role="status">Загрузка каталога…</p>}
    {data && <>
      <div className="grid items-start gap-6 lg:grid-cols-[280px_1fr]">
        <aside className="space-y-4">
          <section className="card"><h2>Категории</h2>
            <label>Фильтр<select aria-label="Фильтр" value={categoryId} onChange={e => setCategoryId(e.target.value)}>
              <option value="">Все категории</option>
              {data.categories.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}
            </select></label>
            {data.categories.filter(category => !categoryId || category.id === categoryId).map(category => <div key={category.id}>
              <h3 className="text-sm">{category.name}</h3><p className="muted whitespace-pre-wrap">{category.description}</p>
            </div>)}
            <button disabled={!data.categories.length} onClick={() => setEditor('new')}>Создать skill</button>
            {!data.categories.length && <p className="muted">Сначала создайте категорию</p>}
          </section>
          <CategoryForm onSaved={resource.refresh} />
        </aside>
        <div className="space-y-4">
          {editor && <SkillForm key={editor === 'new' ? 'new' : editor.id} skill={editor === 'new' ? undefined : editor}
            categories={data.categories} onSaved={resource.refresh} onCancel={() => setEditor(null)} />}
          <div className="grid items-start gap-4 xl:grid-cols-2">
            {filtered?.map(skill => <SkillCard key={skill.id} skill={skill} onEdit={() => setEditor(skill)} onSaved={resource.refresh} />)}
          </div>
          {!filtered?.length && <p className="muted">В этой категории пока нет skills</p>}
        </div>
      </div>
      <section className="space-y-4"><h2>Агенты и назначения</h2>
        <div className="grid items-start gap-5 md:grid-cols-2 xl:grid-cols-3">
          {data.agents.map(agent => <AgentAssignment key={`${agent.id}:${agent.skills.map(skill => `${skill.id}:${skill.enabled}`).join(',')}`} agent={agent} projectName={agent.project_name}
            skills={data.skills} onSaved={resource.refresh} />)}
        </div>
        {!data.agents.length && <p className="muted">Подключите Harness на странице проекта</p>}
      </section>
    </>}
  </>;
}
