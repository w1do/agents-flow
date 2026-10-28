import { Link } from 'react-router-dom';
import type { AgentCardData } from '../api/skills';
import { dateTime, Status } from './Common';

export function AgentCard({ agent, projectName }: { agent: AgentCardData; projectName: string }) {
  return <article className="card">
    <div className="toolbar"><h3>{agent.name}</h3><Status value={agent.status} /></div>
    <p className="muted">Проект: <Link to={`/projects/${agent.project_id}`}>{projectName}</Link></p>
    <p className="muted">Heartbeat: {dateTime(agent.last_heartbeat_at)}</p>
    <p className="break-all text-sm">Git remote: {agent.git_remote || 'Не указан'}</p>
    <p className="muted break-all">Репозиторий: {agent.repository_path_hint || 'Не указан'}</p>
    <div><h3 className="text-sm">Назначенные skills</h3>
      {agent.skills.length ? <ul className="mt-2 space-y-1 text-sm">{agent.skills.map(skill => <li key={skill.id}>
        {skill.name} · v{skill.version}{skill.enabled === false ? ' · отключён' : ''}{!skill.is_active ? ' · архив' : ''}
      </li>)}</ul> : <p className="muted">Нет назначений</p>}
    </div>
    {agent.tasks.map(task => <div key={task.id} className="space-y-2 border-t pt-3">
      <Link to={`/tasks/${task.id}`}>{task.title}</Link>
      <p className="muted">Skills текущей задачи (снимок):</p>
      {task.skill_snapshots.map(snapshot => <p className="text-xs" key={snapshot.id}>
        {snapshot.skill_name} · v{snapshot.skill_version} · <span className="break-all font-mono">{snapshot.content_hash}</span>
      </p>)}
      {!task.skill_snapshots.length && <p className="muted">Снимок пуст</p>}
    </div>)}
  </article>;
}
