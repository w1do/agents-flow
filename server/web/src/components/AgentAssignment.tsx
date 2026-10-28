import { useAgentSkills } from '../api/forms';
import type { AgentCardData } from '../api/skills';
import type { Skill } from '../api/types';
import { AgentCard } from './AgentCard';
import { ErrorNotice } from './Common';

export function AgentAssignment({ agent, skills, projectName, onSaved }: {
  agent: AgentCardData; skills: Skill[]; projectName: string; onSaved: () => Promise<void>;
}) {
  const form = useAgentSkills(agent, skills, onSaved);
  return <div className="space-y-3"><AgentCard agent={agent} projectName={projectName} />
    <form className="card" onSubmit={form.submit} onChange={() => form.setSaved(false)}>
      <h3>Набор skills: {agent.name}</h3><ErrorNotice message={form.action.error} />
      {form.saved && <p role="status" className="text-sm text-emerald-700">Назначения сохранены</p>}
      <fieldset disabled={form.action.busy}>
        {form.available.map(skill => <div className="space-y-1 border-b pb-2" key={skill.id}>
          <label className="flex items-center gap-2"><input type="checkbox" checked={form.selected.includes(skill.id)}
            onChange={e => form.setSelected(ids => e.target.checked ? [...ids, skill.id] : ids.filter(id => id !== skill.id))} />
            <span>{skill.name} · v{skill.version}{!skill.is_active ? ' · архив' : ''}</span>
          </label>
          {form.selected.includes(skill.id) && <label className="flex items-center gap-2 pl-6"><input type="checkbox"
            checked={!form.disabled.includes(skill.id)} onChange={e => form.setDisabled(ids => e.target.checked ? ids.filter(id => id !== skill.id) : [...ids, skill.id])} />
            <span>Включён</span>
          </label>}
        </div>)}
        {!form.available.length && <p className="muted">Создайте активный skill</p>}
        <button type="submit">Сохранить назначения</button>
        <p className="muted">Пустой набор снимает все назначения.</p>
      </fieldset>
    </form>
  </div>;
}
