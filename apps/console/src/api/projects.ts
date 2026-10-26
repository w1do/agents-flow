import type { ProjectInput, ProjectRead, ProjectUpdate } from "@harness/shared-types";

const messages = {
  unauthorized: "Токен не принят. Введите токен оператора заново.",
  invalid_project: "Проверьте отмеченные поля.",
  project_conflict: "Проект с таким id уже существует.",
  project_disabled: "Проект отключён.",
  not_found: "Проект не найден.",
  network_error: "Не удалось связаться с сервером. Повторите запрос.",
  request_failed: "Не удалось выполнить запрос. Повторите попытку.",
};
type ErrorCode = keyof typeof messages;

export class ApiError extends Error {
  constructor(
    public readonly code: ErrorCode,
    public readonly fields: string[] = [],
  ) {
    super(messages[code]);
    this.name = "ApiError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function responseError(status: number, body: unknown): ApiError {
  const detail = record(body) ? body.detail : undefined;
  if (status === 422 && record(detail) && detail.code === "invalid_project") {
    return new ApiError(
      "invalid_project",
      Array.isArray(detail.fields)
        ? detail.fields.filter((field): field is string => typeof field === "string")
        : [],
    );
  }
  if (status === 404 && detail === "not_found") return new ApiError("not_found");
  if (
    status === 409 &&
    (detail === "project_conflict" || detail === "project_disabled")
  ) {
    return new ApiError(detail);
  }
  return new ApiError("request_failed");
}

/** The only HTTP transport; errors never include response text or submitted values. */
export function createProjectsApi(
  token: string,
  onUnauthorized: () => void,
  fetcher = fetch,
) {
  async function request<T>(
    path: string,
    method = "GET",
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetcher(`/api/console/projects${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
        signal,
      });
    } catch {
      throw new ApiError("network_error");
    }
    if (response.status === 401) {
      onUnauthorized();
      throw new ApiError("unauthorized");
    }
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) throw responseError(response.status, payload);
    return payload as T;
  }
  const projectPath = (id: string) => `/${encodeURIComponent(id)}`;
  return {
    list: (signal?: AbortSignal) => request<ProjectRead[]>("", "GET", undefined, signal),
    get: (id: string, signal?: AbortSignal) =>
      request<ProjectRead>(projectPath(id), "GET", undefined, signal),
    create: (data: ProjectInput) => request<ProjectRead>("", "POST", data),
    update: (id: string, data: ProjectUpdate) =>
      request<ProjectRead>(projectPath(id), "PATCH", data),
    disable: (id: string) => request<ProjectRead>(`${projectPath(id)}/disable`, "POST"),
  };
}
export type ProjectsApi = ReturnType<typeof createProjectsApi>;
