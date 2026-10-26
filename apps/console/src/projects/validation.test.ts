import { describe, expect, it } from "vitest";
import { project } from "@/test/fixtures";
import { initialValues, projectInput, projectUpdate } from "./form-values";
import { serverFieldErrors, validateProject } from "./validation";

describe("Валидация формы проекта", () => {
  it.each(["", "-demo", "сайт", "a_b", "a".repeat(29), "a\nb"])(
    "отклоняет неверный id %s",
    (id) => {
      expect(validateProject({ ...initialValues(project), id }, true)).toHaveProperty(
        "id",
      );
    },
  );
  it.each(["A", "1", "Demo-123", "a".repeat(28)])("принимает id на границах %s", (id) => {
    expect(validateProject({ ...initialValues(project), id }, true)).toEqual({});
  });
  it.each(["", "0", "501", "1.5", "no", "Infinity", "-1"])(
    "проверяет лимит ходов %s",
    (agent_max_turns) => {
      expect(
        validateProject({ ...initialValues(project), agent_max_turns }, true),
      ).toHaveProperty("agent_max_turns");
    },
  );
  it.each(["1", "500"])("принимает лимит %s", (agent_max_turns) => {
    expect(validateProject({ ...initialValues(project), agent_max_turns }, true)).toEqual(
      {},
    );
  });
  it("проверяет обязательность, длины и количество названий", () => {
    const values = initialValues(project);
    expect(
      Object.keys(
        validateProject(
          {
            ...values,
            name: "",
            agent: "x".repeat(33),
            default_branch: "x".repeat(129),
            test_command: "x".repeat(2001),
            voice_aliases: Array(21).fill("alias").join("\n"),
            repo: { ...values.repo, project: "x".repeat(256) },
          },
          true,
        ),
      ).sort(),
    ).toEqual([
      "agent",
      "default_branch",
      "name",
      "repo.project",
      "test_command",
      "voice_aliases",
    ]);
    expect(
      validateProject(
        {
          ...values,
          name: "x".repeat(128),
          agent: "x".repeat(32),
          default_branch: "x".repeat(128),
          test_command: "x".repeat(2000),
          voice_aliases: Array(20).fill("alias").join("\n"),
        },
        true,
      ),
    ).toEqual({});
    expect(validateProject({ ...values, voice_aliases: "a\n\n" }, true)).toHaveProperty(
      "voice_aliases",
    );
  });
  it("принимает только ссылку vault и допускает снятие ссылки", () => {
    const values = initialValues(project);
    expect(
      validateProject(
        { ...values, repo: { ...values.repo, access_ref: "private-key" } },
        true,
      ),
    ).toHaveProperty("repo.access_ref");
    expect(
      validateProject({ ...values, repo: { ...values.repo, access_ref: null } }, true),
    ).toEqual({});
  });
  it("очищает команду через null, repo передаёт целиком, id не меняет", () => {
    const values = initialValues(project);
    expect(projectUpdate(values, project)).toEqual({});
    expect(
      projectUpdate(
        {
          ...values,
          id: "different",
          test_command: "",
          repo: { ...values.repo, project: "team/new" },
        },
        project,
      ),
    ).toEqual({ test_command: null, repo: { ...project.repo, project: "team/new" } });
    expect(projectInput({ ...values, voice_aliases: "" }).voice_aliases).toEqual([]);
  });
  it("привязывает только известные имена полей и не повторяет неизвестные значения", () => {
    expect(
      serverFieldErrors(["voice_aliases.1", "repo.access_ref", "private-value"]),
    ).toEqual({ voice_aliases: "Проверьте поле.", "repo.access_ref": "Проверьте поле." });
    expect(serverFieldErrors(["repo"])).toEqual({ repo: "Проверьте поле." });
  });
});
