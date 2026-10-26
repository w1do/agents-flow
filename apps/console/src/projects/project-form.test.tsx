import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/projects";
import { project } from "@/test/fixtures";
import { ProjectForm } from "./project-form";

function renderForm(onSave = vi.fn().mockResolvedValue(undefined), editing = true) {
  render(
    <MemoryRouter>
      <ProjectForm project={editing ? project : undefined} onSave={onSave} />
    </MemoryRouter>,
  );
  return onSave;
}

describe("Форма проекта", () => {
  it("редактирование отправляет только изменения и полный repo со ссылкой", async () => {
    const save = renderForm();
    expect(screen.getByLabelText("ID")).toHaveAttribute("readonly");
    fireEvent.change(screen.getByLabelText("Путь репозитория"), {
      target: { value: "team/new" },
    });
    fireEvent.change(screen.getByLabelText("Команда тестов"), { target: { value: "" } });
    await userEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));
    expect(save).toHaveBeenCalledWith({
      repo: { ...project.repo, project: "team/new" },
      test_command: null,
    });
  });

  it("создание проверяет форму до отправки и показывает подсказки", async () => {
    const save = renderForm(undefined, false);
    await userEvent.click(screen.getByRole("button", { name: "Создать проект" }));
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByLabelText("ID")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Название")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Основная ветка")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
    for (const [label, value] of [
      ["ID", "new-demo"],
      ["Название", "Новый"],
      ["Путь репозитория", "team/demo"],
    ]) {
      fireEvent.change(screen.getByLabelText(label!), { target: { value } });
    }
    await userEvent.click(screen.getByRole("button", { name: "Создать проект" }));
    expect(save).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "new-demo",
        name: "Новый",
        agent_max_turns: 50,
        test_command: null,
      }),
    );
  });

  it("422 подсвечивает только указанные поля, не выводит значения даже из неизвестного поля", async () => {
    const save = vi
      .fn()
      .mockRejectedValue(
        new ApiError("invalid_project", [
          "repo.access_ref",
          "voice_aliases.0",
          "private-value",
        ]),
      );
    renderForm(save);
    await userEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Ссылка на ключ")).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    expect(screen.getByLabelText("Голосовые названия")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByLabelText("Название")).toHaveAttribute("aria-invalid", "false");
    expect(screen.getByRole("alert")).not.toHaveTextContent("vault:demo/git/write");
    expect(document.body.textContent).not.toContain("private-value");
  });

  it("ошибка блока repo отмечает группу без подсветки отдельных полей", async () => {
    renderForm(vi.fn().mockRejectedValue(new ApiError("invalid_project", ["repo"])));
    await userEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));
    expect(await screen.findByRole("group", { name: "Репозиторий" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByLabelText("Путь репозитория")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
    expect(screen.getByLabelText("Адрес сервера репозитория")).toHaveAttribute(
      "aria-invalid",
      "false",
    );
  });

  it.each(["project_conflict", "project_disabled", "not_found"] as const)(
    "показывает понятную ошибку %s",
    async (code) => {
      renderForm(vi.fn().mockRejectedValue(new ApiError(code)));
      await userEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        new ApiError(code).message,
      );
    },
  );

  it("отклоняет значение ключа вместо vault-ссылки без запроса", async () => {
    const save = renderForm();
    fireEvent.change(screen.getByLabelText("Ссылка на ключ"), {
      target: { value: "private-key" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Сохранить изменения" }));
    expect(save).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Ссылка на ключ")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(document.body.textContent).not.toContain("private-key");
  });
});
