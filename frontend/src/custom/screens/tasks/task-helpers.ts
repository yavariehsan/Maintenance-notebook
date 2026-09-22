import type { TaskItem } from '@/lib/api/tasks'

export type TaskStatusKind = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'

/**
 * Map a backend job status to a UI status kind + i18n label key.
 * Backend statuses come from surreal-commands: new/running/completed/failed/canceled.
 */
export function getTaskStatusKind(status: TaskItem['status']): TaskStatusKind {
  switch (status) {
    case 'new':
      return 'pending'
    case 'running':
      return 'processing'
    case 'completed':
      return 'completed'
    case 'failed':
      return 'failed'
    case 'canceled':
      return 'cancelled'
    default:
      return 'pending'
  }
}

export function getTaskStatusLabelKey(status: TaskItem['status']): string {
  // Static map (not a template string) so the i18n unused-key detector,
  // which scans for literal key references, keeps passing.
  const labelKeys: Record<TaskStatusKind, string> = {
    pending: 'tasks.pending',
    processing: 'tasks.processing',
    completed: 'tasks.completed',
    failed: 'tasks.failed',
    cancelled: 'tasks.cancelled',
  }
  return labelKeys[getTaskStatusKind(status)]
}

/** Badge tone per status kind; keeps the page on existing primitives. */
export function getTaskStatusBadgeClass(kind: TaskStatusKind): string {
  switch (kind) {
    case 'processing':
      return 'bg-blue-500/15 text-blue-600 dark:text-blue-400 border-blue-500/30'
    case 'completed':
      return 'bg-green-500/15 text-green-600 dark:text-green-400 border-green-500/30'
    case 'failed':
      return 'bg-red-500/15 text-red-600 dark:text-red-400 border-red-500/30'
    case 'cancelled':
      return 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border-amber-500/30'
    case 'pending':
    default:
      return 'bg-muted text-muted-foreground'
  }
}

/**
 * Human chunk counter: "12 / 351" when the total is known, "12" while the
 * worker is still chunking, "—" when nothing is known yet.
 */
export function formatTaskChunks(task: Pick<TaskItem, 'processed_chunks' | 'total_chunks'>): string {
  const { processed_chunks: processed, total_chunks: total } = task
  if (typeof processed === 'number' && typeof total === 'number') {
    return `${processed} / ${total}`
  }
  if (typeof processed === 'number') {
    return `${processed}`
  }
  return '—'
}

/** Best-effort local date/time; returns '—' for missing/invalid input. */
export function formatTaskTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString()
}
