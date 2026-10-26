import type {
  ProjectInput,
  ProjectRead,
  ProjectRepo,
  ProjectUpdate,
} from "@harness/shared-types";

export type FormValues = Omit<
  Required<ProjectInput>,
  "voice_aliases" | "agent_max_turns" | "test_command" | "repo"
> & {
  voice_aliases: string;
  agent_max_turns: string;
  test_command: string;
  repo: Required<ProjectRepo>;
};

export function initialValues(project?: ProjectRead): FormValues {
  return {
    id: project?.id ?? "",
    name: project?.name ?? "",
    voice_aliases: project?.voice_aliases?.join("\n") ?? "",
    repo: project
      ? {
          ...project.repo,
          base_url: project.repo.base_url ?? `https://${project.repo.provider}.com`,
          access_ref: project.repo.access_ref ?? null,
        }
      : {
          provider: "gitlab",
          base_url: "https://gitlab.com",
          project: "",
          access_ref: null,
        },
    default_branch: project?.default_branch ?? "main",
    test_command: project?.test_command ?? "",
    agent: project?.agent ?? "claude-code",
    agent_max_turns: String(project?.agent_max_turns ?? 50),
  };
}

export function projectInput(values: FormValues): Required<ProjectInput> {
  return {
    ...values,
    repo: { ...values.repo },
    voice_aliases: values.voice_aliases === "" ? [] : values.voice_aliases.split("\n"),
    test_command: values.test_command === "" ? null : values.test_command,
    agent_max_turns: Number(values.agent_max_turns),
  };
}

/** Preserve the latest repo reference, and send only changed top-level fields. */
export function projectUpdate(values: FormValues, original: ProjectRead): ProjectUpdate {
  const current = projectInput(values);
  const baseline = projectInput(initialValues(original));
  return Object.fromEntries(
    Object.entries(current).filter(
      ([key, value]) =>
        key !== "id" &&
        JSON.stringify(value) !== JSON.stringify(baseline[key as keyof typeof baseline]),
    ),
  );
}
