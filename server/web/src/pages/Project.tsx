import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useResource } from '../api/hooks';
import { projectsApi } from '../api/projects';
import { statuses } from '../api/types';
import { AgentCard } from '../components/AgentCard';
import { ErrorNotice, Refresh, Status } from '../components/Common';
import { CreateTask } from '../components/CreateTask';
import { HarnessConnect } from '../components/HarnessConnect';

export function Project() {
  const { id = '' } = useParams();
  const resource = useResource(useCallback(() => projectsApi.detail(id), [id]));
  const data = resource.data;
  return <>
    <Link to="/projects">← Проекты</Link>
    <div className="toolbar"><div><h1>{data?.project.name || 'Проект'}</h1>
      <p className="muted whitespace-pre-wrap">{data?.project.description}</p></div>
      <Refresh loading={resource.loading} onClick={resource.refresh} /></div>
    <ErrorNotice message={resource.error} />
    {!data && resource.loading && <p role="status">Загрузка проекта…</p>}
    {data && <>
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <HarnessConnect key={id} projectId={id} /><CreateTask key={id} projectId={id} onSaved={resource.refresh} />
      </div>
      <section className="space-y-4"><h2>Задачи · {data.tasks.length}</h2>
        {!data.tasks.length && <p className="muted">Задач пока нет</p>}
        <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
          {statuses.map(status => {
            const tasks = data.tasks.filter(task => task.status === status);
            return tasks.length > 0 && <section className="card" key={status}>
              <div className="toolbar"><Status value={status} /><span className="muted">{tasks.length}</span></div>
              {tasks.map(task => <article className="border-t pt-3" key={task.id}>
                <Link to={`/tasks/${task.id}`} className="font-medium">{task.title}</Link>
                <p className="muted mt-1">{data.agents.find(agent => agent.id === task.assigned_agent_id)?.name || 'Без агента'}</p>
              </article>)}
            </section>;
          })}
        </div>
      </section>
      <section className="space-y-4"><h2>Агенты · {data.agents.length}</h2>
        {!data.agents.length && <p className="muted">Подключите Harness, чтобы добавить агента</p>}
        <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.agents.map(agent => <AgentCard key={agent.id} agent={agent} projectName={data.project.name} />)}
        </div>
      </section>
    </>}
  </>;
}
