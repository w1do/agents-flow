import { harnessServer, listAll, request } from './client';
import { loadAgentCards } from './skills';
import type { Agent, InitToken, Project, Task } from './types';

export const projectsApi = {
  async list() {
    const projects = await listAll<Project>('/projects');
    return Promise.all(projects.map(async project => ({
      ...project,
      active_tasks: (await listAll<Task>(`/projects/${project.id}/tasks`))
        .filter(task => ['choosing', 'planning', 'active', 'testing'].includes(task.status)),
    })));
  },
  create: (name: string, description: string) => request<Project>('/projects', {
    method: 'POST', body: { name, description },
  }),
  init: (id: string) => request<InitToken>(`/projects/${id}/init-tokens`, { method: 'POST' }),
  async detail(id: string) {
    const [project, tasks, agents] = await Promise.all([
      request<Project>(`/projects/${id}`), listAll<Task>(`/projects/${id}/tasks`),
      listAll<Agent>(`/projects/${id}/agents`),
    ]);
    return { project, tasks, agents: await loadAgentCards(agents, tasks) };
  },
  createTask: (id: string, title: string, description: string) => request<Task>(`/projects/${id}/tasks`, {
    method: 'POST', body: { title, description, source_type: 'web', source_text: description },
  }),
};

const shellQuote = (value: string) => `'${value.replace(/'/g, `'"'"'`)}'`;
export const initCommand = (projectId: string) =>
  `harness init ${shellQuote(projectId)} --server-url ${shellQuote(harnessServer())}`;
