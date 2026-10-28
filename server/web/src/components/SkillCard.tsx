import { useAction } from '../api/hooks';
import { skillsApi } from '../api/skills';
import type { Skill } from '../api/types';
import { ErrorNotice, Status } from './Common';

export function SkillCard({ skill, onEdit, onSaved }: {
  skill: Skill; onEdit: () => void; onSaved: () => Promise<void>;
}) {
  const action = useAction();
  return <article className="card">
    <div className="toolbar"><h3>{skill.name} · v{skill.version}</h3><Status value={skill.is_active ? 'active' : 'archive'} /></div>
    <p className="whitespace-pre-wrap text-sm">{skill.description || 'Без описания'}</p>
    <p className="break-all font-mono text-xs text-slate-500">{skill.content_hash}</p>
    <p className="muted">Назначен агентам: {skill.assigned_agents.length}</p>
    {skill.warnings.length > 0 && <p className="text-sm text-amber-800">Предупреждения: {skill.warnings.join(', ')}</p>}
    <details><summary className="cursor-pointer text-sm text-indigo-700">Markdown</summary><pre>{skill.content}</pre></details>
    <ErrorNotice message={action.error} />
    <div className="actions"><button className="secondary" onClick={onEdit}>Править</button>
      {skill.is_active && <button disabled={action.busy} className="danger" onClick={() => {
        void action.run(async () => { await skillsApi.archive(skill.id); await onSaved(); });
      }}>Архивировать</button>}
    </div>
  </article>;
}
