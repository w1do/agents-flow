import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { login, mount } from "./test/app-helpers";
import { json, project } from "./test/fixtures";

describe("Консоль проектов", () => {
  it("показывает список активных и отключённых проектов и агента", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation(() =>
          Promise.resolve(
            json([
              project,
              { ...project, id: "disabled", name: "Архив", status: "disabled" },
            ]),
          ),
        ),
    );
    mount();
    await login();
    expect(await screen.findByRole("link", { name: "Демо" })).toBeInTheDocument();
    expect(screen.getByText("disabled", { selector: "span" })).toBeInTheDocument();
    expect(screen.getAllByText("claude-code")).toHaveLength(2);
    expect(screen.getAllByText("team/demo")).toHaveLength(2);
  });

  it("создаёт проект и возвращает его в список", async () => {
    let created = false;
    const fetcher = vi.fn().mockImplementation((_url, init: RequestInit) => {
      if (init.method === "POST") {
        created = true;
        return Promise.resolve(
          json({ ...project, ...JSON.parse(init.body as string) }, 201),
        );
      }
      return Promise.resolve(
        json(created ? [{ ...project, id: "new", name: "Новый" }] : []),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    mount();
    await login();
    await userEvent.click(await screen.findByRole("link", { name: "Создать проект" }));
    for (const [label, value] of [
      ["ID", "new"],
      ["Название", "Новый"],
      ["Путь репозитория", "team/new"],
    ]) {
      fireEvent.change(screen.getByLabelText(label!), { target: { value } });
    }
    await userEvent.click(screen.getByRole("button", { name: "Создать проект" }));
    expect(await screen.findByRole("link", { name: "Новый" })).toBeInTheDocument();
    const call = fetcher.mock.calls.find(([, init]) => init.method === "POST");
    expect(call?.[0]).toBe("/api/console/projects");
    expect(JSON.parse(call?.[1].body)).toMatchObject({
      id: "new",
      repo: { access_ref: null },
    });
  });

  it("читает последний repo, затем PATCH сохраняет access_ref и не отправляет id", async () => {
    const fetcher = vi
      .fn()
      .mockImplementation((url: string, init: RequestInit) =>
        Promise.resolve(
          json(
            init.method === "PATCH"
              ? { ...project, repo: { ...project.repo, project: "team/new" } }
              : url === "/api/console/projects"
                ? [project]
                : project,
          ),
        ),
      );
    vi.stubGlobal("fetch", fetcher);
    mount();
    await login();
    await userEvent.click(await screen.findByRole("link", { name: "Демо" }));
    fireEvent.change(await screen.findByLabelText("Путь репозитория"), {
      target: { value: "team/new" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));
    await waitFor(() =>
      expect(fetcher.mock.calls.some(([, init]) => init.method === "PATCH")).toBe(true),
    );
    const call = fetcher.mock.calls.find(([, init]) => init.method === "PATCH");
    expect(JSON.parse(call?.[1].body)).toEqual({
      repo: { ...project.repo, project: "team/new" },
    });
  });

  it("отключает только после подтверждения и обновляет статус", async () => {
    let disabled = false;
    const fetcher = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      if (init.method === "POST") {
        disabled = true;
        return Promise.resolve(json({ ...project, status: "disabled" }));
      }
      return Promise.resolve(
        json([{ ...project, status: disabled ? "disabled" : "active" }]),
      );
    });
    vi.stubGlobal("fetch", fetcher);
    mount();
    await login();
    await userEvent.click(await screen.findByRole("button", { name: "Отключить" }));
    const dialog = screen.getByRole("alertdialog");
    expect(fetcher.mock.calls.some(([, init]) => init.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Отмена" }));
    expect(disabled).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Отключить" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "Подтвердить отключение",
      }),
    );
    expect(await screen.findByText("disabled", { selector: "span" })).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledWith(
      "/api/console/projects/demo/disable",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.getByRole("button", { name: "Отключить" })).toBeDisabled();
  });
});
