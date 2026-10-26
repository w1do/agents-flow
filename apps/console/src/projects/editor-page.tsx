import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { ProjectInput, ProjectUpdate } from "@harness/shared-types";
import { ApiError, type ProjectsApi } from "@/api/projects";
import { ProjectForm } from "./project-form";
import { DisableProject } from "./disable-project";

export function EditorPage({
  api,
  creating = false,
}: {
  api: ProjectsApi;
  creating?: boolean;
}) {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["project", projectId],
    queryFn: ({ signal }) => api.get(projectId, signal),
    enabled: !creating,
    staleTime: 0,
    // Re-read when opening the editor, without discarding edits on reconnect.
    refetchOnReconnect: false,
  });
  async function save(data: ProjectInput | ProjectUpdate) {
    const updated = creating
      ? await api.create(data as ProjectInput)
      : await api.update(projectId, data as ProjectUpdate);
    client.setQueryData(["project", updated.id], updated);
    await client.invalidateQueries({ queryKey: ["projects"] });
    navigate("/projects");
  }
  return (
    <div className="mx-auto max-w-3xl">
      <Link to="/projects" className="text-sm text-primary hover:underline">
        ← Все проекты
      </Link>
      <div className="page-heading mt-5">
        <div>
          <p className="eyebrow">Настройки проекта</p>
          <h1>{creating ? "Новый проект" : "Редактирование"}</h1>
        </div>
        {!creating && query.data && <DisableProject project={query.data} api={api} />}
      </div>
      {!creating && query.isFetching && <p role="status">Загрузка настроек…</p>}
      {!creating && query.isError && (
        <p role="alert" className="error-box">
          {query.error instanceof ApiError
            ? query.error.message
            : "Не удалось загрузить проект."}
        </p>
      )}
      {creating ? (
        <div className="panel p-6 sm:p-8">
          <ProjectForm key="new" onSave={save} />
        </div>
      ) : (
        query.data &&
        !query.isFetching &&
        !query.isError && (
          <div className="panel p-6 sm:p-8">
            <ProjectForm
              key={`${projectId}:${query.dataUpdatedAt}`}
              project={query.data}
              onSave={save}
            />
          </div>
        )
      )}
    </div>
  );
}
