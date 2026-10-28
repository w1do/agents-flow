import { useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useResource } from '../api/hooks';
import { tasksApi } from '../api/tasks';
import { ErrorNotice, Refresh, Status } from '../components/Common';
import { TaskDecisions } from '../components/TaskDecisions';
import { TaskDetails } from '../components/TaskDetails';

export function Task() {
  const { id = '' } = useParams();
  const resource = useResource(useCallback(() => tasksApi.get(id), [id]));
  const task = resource.data;
  return <>
    <div className="toolbar"><h1>{task?.title || 'Задача'}</h1><Refresh loading={resource.loading} onClick={resource.refresh} /></div>
    <ErrorNotice message={resource.error} />
    {!task && resource.loading && <p role="status">Загрузка задачи…</p>}
    {task && <>
      <div className="toolbar"><Link to={`/projects/${task.project_id}`}>← К проекту</Link><Status value={task.status} /></div>
      <p className="whitespace-pre-wrap text-sm">{task.description}</p>
      <TaskDecisions key={task.id} task={task} onSaved={resource.refresh} />
      <TaskDetails task={task} />
    </>}
  </>;
}
