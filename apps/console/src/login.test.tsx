import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { login, mount } from "./test/app-helpers";
import { json, project } from "./test/fixtures";

describe("Вход оператора", () => {
  it("не хранит токен, при 401 возвращается на вход и после перемонтирования просит его снова", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const fetcher = vi
      .fn()
      .mockImplementation(() => Promise.resolve(json({ detail: "test-token" }, 401)));
    vi.stubGlobal("fetch", fetcher);
    const view = mount();
    await login();
    expect(await screen.findByRole("heading", { name: "Вход" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).not.toHaveTextContent("test-token");
    expect(screen.getByLabelText("Токен оператора")).toHaveValue("");
    expect(storage).not.toHaveBeenCalled();
    view.unmount();
    mount();
    expect(screen.getByLabelText("Токен оператора")).toHaveValue("");
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("при выходе удаляет данные проекта и снова требует токен", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => Promise.resolve(json([project]))),
    );
    mount();
    await login();
    expect(await screen.findByRole("link", { name: "Демо" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Выйти" }));
    expect(screen.getByRole("heading", { name: "Вход" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Демо" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Токен оператора")).toHaveValue("");
  });

  it("при 401 во время отключения возвращается на вход", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation((_url: string, init: RequestInit) =>
          Promise.resolve(
            init.method === "POST"
              ? json({ detail: "test-token" }, 401)
              : json([project]),
          ),
        ),
    );
    mount();
    await login();
    await userEvent.click(await screen.findByRole("button", { name: "Отключить" }));
    await userEvent.click(screen.getByRole("button", { name: "Подтвердить отключение" }));
    expect(await screen.findByRole("heading", { name: "Вход" })).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });
});
