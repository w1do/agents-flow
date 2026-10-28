import { listAll, request } from './client';
import type { Agent, Category, Project, Skill, Task } from './types';

export interface AgentCardData extends Agent {
  skills: Skill[];
  tasks: Task[];
}
export type SkillInput = Pick<Skill, 'name' | 'description' | 'content' | 'category_id'>;

export async function loadAgentCards(agents: Agent[], tasks: Task[]): Promise<AgentCardData[]> {
  return Promise.all(agents.map(async agent => ({
    ...agent,
    skills: await skillsApi.assigned(agent.id),
    tasks: tasks.filter(task => task.assigned_agent_id === agent.id && !task.completed_at &&
      ['choosing', 'planning', 'backlog', 'active', 'testing', 'ready', 'merged'].includes(task.status)),
  })));
}

export const skillsApi = {
  assigned: (id: string) => request<Skill[]>(`/agents/${id}/skills`),
  assign: (id: string, skill_ids: string[], disabled_skill_ids: string[]) => request<Skill[]>(`/agents/${id}/skills`, {
    method: 'PUT', body: { skill_ids, disabled_skill_ids },
  }),
  category: (name: string, description: string) => request<Category>('/skill-categories', {
    method: 'POST', body: { name, description },
  }),
  save: (input: SkillInput, id?: string) => request<Skill>(id ? `/skills/${id}` : '/skills', {
    method: id ? 'PATCH' : 'POST', body: input,
  }),
  archive: (id: string) => request<Skill>(`/skills/${id}/archive`, { method: 'POST' }),
  async catalog() {
    const [categories, skills, projects] = await Promise.all([
      listAll<Category>('/skill-categories'), listAll<Skill>('/skills'), listAll<Project>('/projects'),
    ]);
    const agents = (await Promise.all(projects.map(async project => ({
      project, cards: await loadAgentCards(await listAll<Agent>(`/projects/${project.id}/agents`),
        await listAll<Task>(`/projects/${project.id}/tasks`)),
    })))).flatMap(({ project, cards }) => cards.map(agent => ({ ...agent, project_name: project.name })));
    return { categories: categories.sort((a, b) => a.sort_order - b.sort_order), skills, agents };
  },
};
