import type { FormValues } from "./form-values";

export const fieldLabels = {
  id: "ID",
  name: "Название",
  voice_aliases: "Голосовые названия",
  repo: "Репозиторий",
  "repo.provider": "Провайдер",
  "repo.base_url": "Адрес сервера репозитория",
  "repo.project": "Путь репозитория",
  "repo.access_ref": "Ссылка на ключ",
  default_branch: "Основная ветка",
  test_command: "Команда тестов",
  agent: "Агент",
  agent_max_turns: "Максимум ходов агента",
} as const;
export type FieldName = keyof typeof fieldLabels;
export type FieldErrors = Partial<Record<FieldName, string>>;

export function serverFieldErrors(fields: string[]): FieldErrors {
  const errors: FieldErrors = {};
  for (const raw of fields) {
    const field = raw.replace(/\.\d+$/, "");
    if (Object.hasOwn(fieldLabels, field)) {
      errors[field as FieldName] = "Проверьте поле.";
    }
  }
  return errors;
}

export function validateProject(values: FormValues, creating: boolean): FieldErrors {
  const errors: FieldErrors = {};
  if (creating && !/^[A-Za-z0-9][A-Za-z0-9-]{0,27}$/.test(values.id)) {
    errors.id =
      "От 1 до 28 латинских букв, цифр и дефисов; первый символ — буква или цифра.";
  }
  for (const [field, max] of [
    ["name", 128],
    ["default_branch", 128],
    ["agent", 32],
  ] as const) {
    if (!values[field].trim()) errors[field] = "Заполните поле.";
    else if ([...values[field]].length > max) errors[field] = `Не более ${max} символов.`;
  }
  if (!values.repo.project.trim() || [...values.repo.project].length > 255) {
    errors["repo.project"] = "Укажите путь репозитория длиной до 255 символов.";
  }
  if (!values.repo.base_url.trim())
    errors["repo.base_url"] = "Укажите HTTPS-адрес сервера.";
  const aliases = values.voice_aliases === "" ? [] : values.voice_aliases.split("\n");
  if (aliases.length > 20 || aliases.some((alias) => !alias.trim())) {
    errors.voice_aliases = "До 20 непустых названий, каждое на отдельной строке.";
  }
  if (
    !/^\d+$/.test(values.agent_max_turns) ||
    Number(values.agent_max_turns) < 1 ||
    Number(values.agent_max_turns) > 500
  ) {
    errors.agent_max_turns = "Целое число от 1 до 500.";
  }
  if ([...values.test_command].length > 2000)
    errors.test_command = "Не более 2000 символов.";
  const part = "[^/\\s](?:[^/\\r\\n]*[^/\\s])?";
  if (
    values.repo.access_ref &&
    !new RegExp(`^vault:${part}/${part}/${part}$`, "u").test(values.repo.access_ref)
  ) {
    errors["repo.access_ref"] = "Ожидается ссылка vault:проект/сервис/имя.";
  }
  return errors;
}
