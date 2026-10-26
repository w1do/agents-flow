/* Generated from harness_shared.projects. Run pnpm types:generate; do not edit. */

export type Id = string;
export type Name = string;
/**
 * @maxItems 20
 */
export type VoiceAliases = string[];
export type Provider = "github" | "gitlab";
export type BaseUrl = string;
export type Project = string;
export type AccessRef = string | null;
export type DefaultBranch = string;
export type TestCommand = string | null;
export type Agent = string;
export type AgentMaxTurns = number;
export type Id1 = string;
export type Name1 = string;
/**
 * @maxItems 20
 */
export type VoiceAliases1 = string[];
export type DefaultBranch1 = string;
export type TestCommand1 = string | null;
export type Agent1 = string;
export type AgentMaxTurns1 = number;
/**
 * Статус проекта: disabled не принимает новые задачи и не выдаётся машине агента (D-65).
 *
 * This interface was referenced by `Projects`'s JSON-Schema
 * via the `definition` "ProjectStatus".
 */
export type ProjectStatus = "active" | "disabled";
export type UpdatedAt = string;
export type Name2 = string | null;
export type VoiceAliases2 = string[] | null;
export type DefaultBranch2 = string | null;
export type TestCommand2 = string | null;
export type Agent2 = string | null;
export type AgentMaxTurns2 = number | null;

export interface Projects {}
/**
 * Поля, которые оператор задаёт при создании проекта. Лишние поля отклоняются.
 *
 * This interface was referenced by `Projects`'s JSON-Schema
 * via the `definition` "ProjectInput".
 */
export interface ProjectInput {
  id: Id;
  name: Name;
  voice_aliases?: VoiceAliases;
  repo: ProjectRepo;
  default_branch?: DefaultBranch;
  test_command?: TestCommand;
  agent?: Agent;
  agent_max_turns?: AgentMaxTurns;
}
/**
 * Репозиторий проекта (D-60): провайдер, адрес, проект и необязательная ссылка на ключ записи.
 *
 * Адрес по умолчанию зависит от провайдера. Ключ не хранится: access_ref — только ссылка vault.
 * Без access_ref клон анонимный и подходит только для публичного репозитория.
 *
 * This interface was referenced by `Projects`'s JSON-Schema
 * via the `definition` "ProjectRepo".
 */
export interface ProjectRepo {
  provider: Provider;
  base_url?: BaseUrl;
  project: Project;
  access_ref?: AccessRef;
}
/**
 * Проект, как его видит оператор: с присвоенным статусом и временем изменения.
 *
 * This interface was referenced by `Projects`'s JSON-Schema
 * via the `definition` "ProjectRead".
 */
export interface ProjectRead {
  id: Id1;
  name: Name1;
  voice_aliases?: VoiceAliases1;
  repo: ProjectRepo;
  default_branch?: DefaultBranch1;
  test_command?: TestCommand1;
  agent?: Agent1;
  agent_max_turns?: AgentMaxTurns1;
  status: ProjectStatus;
  updated_at: UpdatedAt;
}
/**
 * Частичное изменение: передаются только изменяемые поля. id меняется только созданием.
 *
 * Блок repo передаётся целиком: без access_ref в нём ссылка на ключ снимается.
 *
 * This interface was referenced by `Projects`'s JSON-Schema
 * via the `definition` "ProjectUpdate".
 */
export interface ProjectUpdate {
  name?: Name2;
  voice_aliases?: VoiceAliases2;
  repo?: ProjectRepo | null;
  default_branch?: DefaultBranch2;
  test_command?: TestCommand2;
  agent?: Agent2;
  agent_max_turns?: AgentMaxTurns2;
}
