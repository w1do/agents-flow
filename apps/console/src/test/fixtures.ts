import type { ProjectRead } from "@harness/shared-types";

export const project: ProjectRead = {
  id: "demo",
  name: "Демо",
  voice_aliases: ["демо"],
  repo: {
    provider: "gitlab",
    base_url: "https://gitlab.com",
    project: "team/demo",
    access_ref: "vault:demo/git/write",
  },
  default_branch: "main",
  test_command: "pnpm test",
  agent: "claude-code",
  agent_max_turns: 50,
  status: "active",
  updated_at: "2026-10-26T00:00:00Z",
};

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
