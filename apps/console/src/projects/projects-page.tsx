import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, type ProjectsApi } from "@/api/projects";
import { Button } from "@/components/ui/button";
import { DisableProject } from "./disable-project";

export function ProjectsPage({ api }: { api: ProjectsApi }) {
  const query = useQuery({
    queryKey: ["projects"],
    queryFn: ({ signal }) => api.list(signal),
    refetchInterval: 5000,
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">Каталог харнесса</p>
          <h1>Проекты</h1>
          <p className="text-muted-foreground">
            Репозитории, команды тестов и настройки запуска агента.
          </p>
        </div>
        <Button asChild>
          <Link to="/projects/new">Создать проект</Link>
        </Button>
      </div>
      {query.isPending && <p role="status">Загрузка проектов…</p>}
      {query.isError && (
        <div className="error-box" role="alert">
          <p>
            {query.error instanceof ApiError
              ? query.error.message
              : "Не удалось загрузить проекты."}
          </p>
          <Button variant="outline" onClick={() => void query.refetch()}>
            Повторить
          </Button>
        </div>
      )}
      {query.data && (
        <div className="panel overflow-x-auto">
          <table>
            <caption className="sr-only">Все проекты, включая отключённые</caption>
            <thead>
              <tr>
                <th>ID / Название</th>
                <th>Статус</th>
                <th>Репозиторий</th>
                <th>Агент</th>
                <th>
                  <span className="sr-only">Действия</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {query.data.map((project) => (
                <tr key={project.id}>
                  <td>
                    <Link
                      className="font-semibold text-primary hover:underline"
                      to={`/projects/${encodeURIComponent(project.id)}`}
                    >
                      {project.name}
                    </Link>
                    <p className="mt-1 font-mono text-xs text-muted-foreground">
                      {project.id}
                    </p>
                  </td>
                  <td>
                    <span
                      className={
                        project.status === "active"
                          ? "badge bg-emerald-50 text-emerald-800"
                          : "badge bg-slate-100 text-slate-600"
                      }
                    >
                      {project.status}
                    </span>
                  </td>
                  <td>
                    <p className="font-medium">{project.repo.project}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {project.repo.provider} · {project.repo.base_url}
                    </p>
                  </td>
                  <td className="font-mono text-xs">{project.agent}</td>
                  <td>
                    <div className="flex gap-2">
                      <Button variant="outline" asChild>
                        <Link
                          aria-label={`Редактировать ${project.name}`}
                          to={`/projects/${encodeURIComponent(project.id)}`}
                        >
                          Настройки
                        </Link>
                      </Button>
                      <DisableProject project={project} api={api} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {query.data.length === 0 && (
            <p className="p-12 text-center text-muted-foreground">
              Проектов пока нет. Создайте первый проект.
            </p>
          )}
        </div>
      )}
    </>
  );
}
