export interface Agent {
  id: string;
  project_id: string;
  name: string;
  status: string;
  last_heartbeat_at: string | null;
  git_remote: string;
  repository_path_hint: string;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  active_task_count: number;
  agents: Agent[];
  init_code_expires_at: string | null;
}

export interface Category {
  id: string;
  name: string;
  description: string;
  sort_order: number;
}

export interface Skill {
  id: string;
  category_id: string;
  name: string;
  description: string;
  content: string;
  version: number;
  content_hash: string;
  is_active: boolean;
  warnings: string[];
  assigned_agents: string[];
  enabled: boolean | null;
}

export const statuses = ['new', 'choosing', 'planning', 'backlog', 'active', 'testing',
  'ready', 'merged', 'error', 'stalled', 'paused', 'trash'] as const;
export type TaskStatus = typeof statuses[number];

export interface TaskEvent {
  id: string;
  event_type: string;
  message: string;
  payload: Record<string, unknown> | null;
  created_at: string;
}

export interface Snapshot {
  id: string;
  skill_name: string;
  category: string;
  skill_version: number;
  content_hash: string;
  content_missing: boolean;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  description: string;
  status: TaskStatus;
  assigned_agent_id: string | null;
  plan_text: string | null;
  plan_revision: number;
  plan_decision: string;
  plan_feedback: string | null;
  result_summary: string | null;
  result_data: Record<string, unknown> | null;
  checkpoint: Record<string, unknown> | null;
  completed_at: string | null;
  events: TaskEvent[];
  skill_snapshots: Snapshot[];
}

export interface InitToken { code: string; expires_at: string }
export type PlanDecision = 'approved' | 'rejected' | 'trash';
export type ResultDecision = 'publish' | 'rework' | 'keep_ready';
