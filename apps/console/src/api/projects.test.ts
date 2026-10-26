import { describe, expect, it, vi } from "vitest";
import { ApiError, createProjectsApi } from "./projects";
import { json, project } from "@/test/fixtures";

describe("Клиент API с токеном", () => {
  it("передаёт Bearer во все запросы, кодирует id и не отправляет cookie", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(project));
    const api = createProjectsApi("test-operator-token", vi.fn(), fetcher);
    await api.list();
    await api.get("a/b");
    const input = { id: project.id, name: project.name, repo: project.repo };
    await api.create(input);
    await api.update("demo", { name: "Новое" });
    await api.disable("demo");
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/console/projects",
      "/api/console/projects/a%2Fb",
      "/api/console/projects",
      "/api/console/projects/demo",
      "/api/console/projects/demo/disable",
    ]);
    expect(fetcher.mock.calls.map(([, init]) => init.method)).toEqual([
      "GET",
      "GET",
      "POST",
      "PATCH",
      "POST",
    ]);
    for (const [url, init] of fetcher.mock.calls) {
      expect(init.headers.Authorization).toBe("Bearer test-operator-token");
      expect(init).toMatchObject({
        credentials: "omit",
        redirect: "error",
        cache: "no-store",
      });
      expect(url).not.toContain("test-operator-token");
    }
    expect(JSON.parse(fetcher.mock.calls[3]![1].body)).toEqual({ name: "Новое" });
  });

  it("при 401 отзывает доступ без чтения текста ответа", async () => {
    const exit = vi.fn();
    const api = createProjectsApi(
      "private-token",
      exit,
      vi.fn().mockResolvedValue(json({ detail: "private-token" }, 401)),
    );
    await expect(api.list()).rejects.toMatchObject({ code: "unauthorized" });
    expect(exit).toHaveBeenCalledOnce();
  });

  it.each([
    [404, { detail: "not_found" }, "not_found"],
    [409, { detail: "project_conflict" }, "project_conflict"],
    [409, { detail: "project_disabled" }, "project_disabled"],
    [
      422,
      { detail: { code: "invalid_project", fields: ["repo.access_ref"] } },
      "invalid_project",
    ],
    [500, { detail: "private-value" }, "request_failed"],
  ])("ошибка %s переводится по коду без значений", async (status, body, code) => {
    const api = createProjectsApi(
      "private-token",
      vi.fn(),
      vi.fn().mockResolvedValue(json(body, status)),
    );
    const error = await api.list().catch((value: unknown) => value);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ code });
    expect(String(error)).not.toContain("private-value");
    expect(String(error)).not.toContain("private-token");
  });

  it("не показывает текст сетевой ошибки или не-JSON ответа", async () => {
    const api = createProjectsApi(
      "private-token",
      vi.fn(),
      vi.fn().mockRejectedValue(new Error("private-value")),
    );
    await expect(api.list()).rejects.toMatchObject({ code: "network_error" });
    const malformed = createProjectsApi(
      "private-token",
      vi.fn(),
      vi.fn().mockResolvedValue(new Response("private-value", { status: 502 })),
    );
    await expect(malformed.list()).rejects.toMatchObject({ code: "request_failed" });
  });
});
