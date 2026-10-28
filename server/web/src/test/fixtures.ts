import type { Skill, Task } from '../api/types';

export const task: Task = {
  id: 'task-id', project_id: 'project-id', title: 'Implement panel', description: 'Build UI',
  status: 'ready', assigned_agent_id: null, plan_text: 'A plan', plan_revision: 2,
  plan_decision: 'approved', plan_feedback: null, result_summary: 'Implemented',
  result_data: { changed_paths: ['app.ts'], tests: [{ success: true }] }, checkpoint: null,
  events: [], skill_snapshots: [], completed_at: null,
};

export const skill: Skill = {
  id: 'skill-id', name: 'Testing', category_id: 'category-id', description: 'Run tests',
  content: '# Run tests', version: 1, content_hash: 'hash-v1', is_active: true,
  warnings: [], assigned_agents: [], enabled: true,
};
export const category = { id: 'category-id', name: 'Engineering', description: '', sort_order: 0 };
