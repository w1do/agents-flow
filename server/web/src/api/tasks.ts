import { request } from './client';
import type { PlanDecision, ResultDecision, Task } from './types';

export const tasksApi = {
  get: (id: string) => request<Task>(`/tasks/${id}`),
  plan: (id: string, decision: PlanDecision, feedback: string) => request<Task>(`/tasks/${id}/plan/decision`, {
    method: 'POST', body: { decision, feedback: feedback || null },
  }),
  result: (id: string, decision: ResultDecision, feedback: string) => request<Task>(`/tasks/${id}/result/decision`, {
    method: 'POST', body: { decision, feedback: feedback || null },
  }),
  status: (id: string, status: 'new' | 'paused' | 'trash') => request<Task>(`/tasks/${id}`, {
    method: 'PATCH', body: { status },
  }),
};
