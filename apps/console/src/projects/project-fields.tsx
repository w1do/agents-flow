import type { ReactNode } from "react";
import { Input } from "@/components/ui/input";
import type { FormValues } from "./form-values";
import { type FieldErrors, type FieldName } from "./validation";
import { ProjectField, type ControlProps } from "./project-field";

interface Props {
  values: FormValues;
  errors: FieldErrors;
  creating: boolean;
  onChange: (values: FormValues) => void;
}

export function ProjectFields({ values, errors, creating, onChange }: Props) {
  function field(
    name: FieldName,
    control: (props: ControlProps) => ReactNode,
    hint?: string,
  ) {
    return (
      <ProjectField key={name} name={name} error={errors[name]} hint={hint}>
        {control}
      </ProjectField>
    );
  }
  function text(name: "id" | "name" | "default_branch" | "agent" | "agent_max_turns") {
    return field(name, (props) => (
      <Input
        {...props}
        value={values[name]}
        readOnly={name === "id" && !creating}
        inputMode={name === "agent_max_turns" ? "numeric" : undefined}
        onChange={(event) => onChange({ ...values, [name]: event.target.value })}
      />
    ));
  }
  function repoText(name: "base_url" | "project" | "access_ref", hint?: string) {
    return field(
      `repo.${name}`,
      (props) => (
        <Input
          {...props}
          value={values.repo[name] ?? ""}
          autoComplete="off"
          spellCheck={false}
          onChange={(event) =>
            onChange({
              ...values,
              repo: {
                ...values.repo,
                [name]:
                  name === "access_ref" && event.target.value === ""
                    ? null
                    : event.target.value,
              },
            })
          }
        />
      ),
      hint,
    );
  }
  return (
    <div className="space-y-7">
      <fieldset className="form-grid">
        <legend>Проект</legend>
        {text("id")}
        {text("name")}
        {field(
          "voice_aliases",
          (props) => (
            <textarea
              {...props}
              className="control min-h-24"
              value={values.voice_aliases}
              onChange={(event) =>
                onChange({ ...values, voice_aliases: event.target.value })
              }
            />
          ),
          "До 20 названий, каждое на отдельной строке.",
        )}
      </fieldset>
      <fieldset
        className="form-grid"
        aria-invalid={Boolean(errors.repo)}
        aria-describedby={errors.repo ? "repo-error" : undefined}
      >
        <legend>Репозиторий</legend>
        {errors.repo && (
          <p id="repo-error" className="field-error sm:col-span-2">
            {errors.repo}
          </p>
        )}
        {field("repo.provider", (props) => (
          <select
            {...props}
            className="control"
            value={values.repo.provider}
            onChange={(event) => {
              const provider = event.target.value === "github" ? "github" : "gitlab";
              const defaults = ["https://github.com", "https://gitlab.com"];
              onChange({
                ...values,
                repo: {
                  ...values.repo,
                  provider,
                  base_url: defaults.includes(values.repo.base_url)
                    ? `https://${provider}.com`
                    : values.repo.base_url,
                },
              });
            }}
          >
            <option value="gitlab">GitLab</option>
            <option value="github">GitHub</option>
          </select>
        ))}
        {repoText("base_url", "HTTPS-адрес без учётных данных.")}
        {repoText("project", "group/name или group/subgroup/name, без .git.")}
        {repoText(
          "access_ref",
          "Только ссылка vault:проект/сервис/имя. Оставьте пустым для анонимного доступа.",
        )}
      </fieldset>
      <fieldset className="form-grid">
        <legend>Запуск агента</legend>
        {text("default_branch")}
        {text("agent")}
        {text("agent_max_turns")}
        {field(
          "test_command",
          (props) => (
            <textarea
              {...props}
              className="control min-h-24 font-mono"
              value={values.test_command}
              onChange={(event) =>
                onChange({ ...values, test_command: event.target.value })
              }
            />
          ),
          "Пустое поле очищает команду тестов.",
        )}
      </fieldset>
    </div>
  );
}
