import apiClient from './client'

export type TaskStatus = 'new' | 'running' | 'completed' | 'failed' | 'canceled' | string

export interface TaskItem {
  job_id: string
  item_type: string
  source_id?: string | null
  source_title?: string | null
  status: TaskStatus
  processed_chunks?: number | null
  total_chunks?: number | null
  /** processed/total*100 when the worker reported a total, else null (indeterminate). */
  percentage?: number | null
  chunks_created?: number | null
  created?: string | null
  updated?: string | null
  started_at?: string | null
  updated_at?: string | null
  error_message?: string | null
}

export const ACTIVE_TASK_STATUSES: ReadonlySet<string> = new Set(['new', 'running'])

export function isActiveTask(task: Pick<TaskItem, 'status'>): boolean {
  return ACTIVE_TASK_STATUSES.has(task.status)
}

export const tasksApi = {
  list: async (limit = 50): Promise<TaskItem[]> => {
    const response = await apiClient.get<TaskItem[]>('/tasks', { params: { limit } })
    return response.data
  },
}
