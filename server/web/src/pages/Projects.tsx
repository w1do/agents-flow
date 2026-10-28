import { Link } from 'react-router-dom';
import { projectsApi } from '../api/projects';
import { useResource } from '../api/hooks';
import { ErrorNotice, Refresh, Status } from '../components/Common';
import { CreateProject } from '../components/CreateProject';

export function Projects() {
  const resource = useResource(projectsApi.list);
  return <>
    <div className="toolbar"><div><h1>Проекты</h1><p className="muted">Данные обновляются каждые 15 секунд.</p></div>
      <Refresh loading={resource.loading} onClick={resource.refresh} /></div>
    <ErrorNotice message={resource.error} />
    <div className="grid items-start gap-6 lg:grid-cols-[1fr_340px]">
      <div className="grid gap-4 md:grid-cols-2">
        {resource.data?.map(project => <article className="card" key={project.id}>
          <h2><Link to={`/projects/${project.id}`}>{project.name}</Link></h2>
          <p className="whitespace-pre-wrap text-sm">{project.description || 'Без описания'}</p>
          <p className="muted">Активных задач: <strong className="text-slate-900">{project.active_task_count}</strong></p>
          {project.active_tasks.length > 0 && <ul className="space-y-2 text-sm">{project.active_tasks.map(task => <li key={task.id} className="toolbar">
            <Link to={`/tasks/${task.id}`}>{task.title}</Link><Status value={task.status} />
          </li>)}</ul>}
          <div className="space-y-2">
            {project.agents.map(agent => <div key={agent.id} className="toolbar text-sm"><span>{agent.name}</span><Status value={agent.status} /></div>)}
            {!project.agents.length && <p className="muted">Агенты ещё не подключены</p>}
          </div>
        </article>)}
        {resource.data?.length === 0 && <p className="muted">Проектов пока нет. Создайте первый.</p>}
        {!resource.data && resource.loading && <p role="status">Загрузка проектов…</p>}
      </div>
      <CreateProject onSaved={resource.refresh} />
    </div>
  </>;
}
