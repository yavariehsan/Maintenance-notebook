'use client'

import { Fragment, useState } from 'react'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { AlertCircle, ListTodo, RefreshCw, Trash2 } from 'lucide-react'
import { useDeleteTask, useClearTasksHistory, useTasks } from '@/lib/hooks/use-tasks'
import { useTranslation } from '@/lib/hooks/use-translation'
import { isActiveTask, type TaskItem } from '@/lib/api/tasks'
import {
  formatTaskChunks,
  formatTaskTime,
  getTaskStatusBadgeClass,
  getTaskStatusKind,
  getTaskStatusLabelKey,
} from './task-helpers'

/**
 * Downstream Tasks screen. Shows background embedding jobs submitted via
 * "Embed Content" with real worker-reported progress (processed/total
 * chunks). Polling is bounded: it runs only while a job is active.
 * Terminal job records can be deleted (command row only — never files,
 * reports, or knowledge) through an explicit confirm dialog.
 */
function TaskDetail({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate font-medium">{value || '—'}</dd>
    </div>
  )
}

function TaskProgressCell({ task }: { task: TaskItem }) {
  const { t } = useTranslation()
  if (typeof task.percentage === 'number') {
    return (
      <div className="flex items-center gap-2">
        <Progress value={Math.min(100, Math.max(0, task.percentage))} className="w-24" />
        <span className="text-sm tabular-nums">{task.percentage}%</span>
      </div>
    )
  }
  if (isActiveTask(task)) {
    // Honest indeterminate state: the worker hasn't reported a total yet.
    return (
      <div className="flex items-center gap-2">
        <div className="h-2 w-24 overflow-hidden rounded-full bg-primary/20">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
        </div>
        <span className="text-sm text-muted-foreground">{t('tasks.inProgress')}</span>
      </div>
    )
  }
  return <span className="text-sm text-muted-foreground">—</span>
}

export function TasksScreen() {
  const { t } = useTranslation()
  const { data: tasks, isLoading, isError, refetch } = useTasks()
  const deleteMutation = useDeleteTask()
  const clearHistoryMutation = useClearTasksHistory()
  const [pendingDelete, setPendingDelete] = useState<TaskItem | null>(null)
  const [confirmClearHistory, setConfirmClearHistory] = useState(false)

  const renderContent = () => {
    if (isLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      )
    }

    if (isError) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('tasks.loadFailed')}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              className="shrink-0"
            >
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }

    if (!tasks || tasks.length === 0) {
      return (
        <EmptyState
          icon={ListTodo}
          title={t('tasks.emptyTitle')}
          description={t('tasks.emptyDescription')}
        />
      )
    }

    return (
      <div className="rounded-md border border-[var(--custom-border)] bg-[var(--custom-surface)] overflow-auto">
        <table className="w-full min-w-[960px] outline-none table-fixed">
          <colgroup>
            <col className="w-auto" />
            <col className="w-[130px]" />
            <col className="w-[210px]" />
            <col className="w-[110px]" />
            <col className="w-[180px] hidden md:table-column" />
            <col className="w-[90px]" />
          </colgroup>
          <thead className="sticky top-0 bg-background z-10">
            <tr className="border-b">
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('tasks.source')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('tasks.status')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('tasks.progress')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('tasks.chunks')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground hidden md:table-cell">
                {t('tasks.lastUpdate')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('tasks.actionsColumn')}
              </th>
            </tr>
          </thead>
          <tbody>
            {tasks.map((task) => {
              const kind = getTaskStatusKind(task.status)
              const deletable = !isActiveTask(task)
              return (
                <Fragment key={task.job_id}>
                  <tr className="border-b transition-colors hover:bg-[var(--surface-raised)]">
                    <td className="h-12 px-4">
                      <div className="flex flex-col overflow-hidden">
                        <span className="font-medium truncate">
                          {task.title || task.source_title || task.source_id || task.job_id}
                        </span>
                        <span className="text-xs text-muted-foreground truncate font-mono">
                          {task.source_id || task.run_id || task.job_id}
                        </span>
                      </div>
                    </td>
                    <td className="h-12 px-4">
                      <Badge variant="outline" className={getTaskStatusBadgeClass(kind)}>
                        {t(getTaskStatusLabelKey(task.status))}
                      </Badge>
                    </td>
                    <td className="h-12 px-4">
                      <TaskProgressCell task={task} />
                    </td>
                    <td className="h-12 px-4 text-sm tabular-nums">
                      <span
                        title={
                          typeof task.processed_chunks === 'number' &&
                          typeof task.total_chunks === 'number'
                            ? `${t('tasks.processed')}: ${task.processed_chunks} · ${t('tasks.total')}: ${task.total_chunks}`
                            : undefined
                        }
                      >
                        {formatTaskChunks(task)}
                      </span>
                    </td>
                    <td className="h-12 px-4 text-sm text-muted-foreground truncate hidden md:table-cell">
                      {formatTaskTime(task.updated_at || task.updated || task.started_at)}
                    </td>
                    <td className="h-12 px-4">
                      {deletable ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setPendingDelete(task)}
                          disabled={deleteMutation.isPending}
                          aria-label={t('tasks.deleteTask')}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      ) : (
                        <span className="text-sm text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                  {task.status === 'failed' && task.error_message ? (
                    <tr className="border-b bg-[var(--surface-raised)]">
                      <td colSpan={6} className="px-4 py-3">
                        <dl className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-2 text-sm">
                          <TaskDetail label={t('tasks.error')} value={task.error_message} />
                          <TaskDetail label={t('tasks.started')} value={formatTaskTime(task.started_at)} />
                        </dl>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-[var(--custom-page)] text-[var(--custom-foreground)]">
        <div className="p-6 space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="font-display text-2xl font-bold tracking-tight">{t('tasks.title')}</h1>
              <p className="mt-1 text-sm text-muted-foreground">{t('tasks.description')}</p>
            </div>
            {tasks && tasks.length > 0 && (
              <div className="flex gap-2">
                <Button
                  onClick={() => setConfirmClearHistory(true)}
                  variant="outline"
                  disabled={clearHistoryMutation.isPending}
                >
                  {t('tasks.clearHistory')}
                </Button>
                <Button onClick={() => refetch()} variant="outline">
                  <RefreshCw className="h-4 w-4 me-2" />
                  {t('common.refresh')}
                </Button>
              </div>
            )}
          </div>

          {renderContent()}
        </div>
      </div>
      <AlertDialog open={pendingDelete !== null} onOpenChange={(open) => { if (!open) setPendingDelete(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('tasks.deleteTaskTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('tasks.deleteTaskDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (pendingDelete) {
                  deleteMutation.mutate(pendingDelete.job_id, {
                    onSuccess: () => setPendingDelete(null),
                  })
                }
              }}
            >
              {t('tasks.deleteTask')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={confirmClearHistory} onOpenChange={setConfirmClearHistory}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('tasks.clearHistoryTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('tasks.clearHistoryDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={clearHistoryMutation.isPending}>
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={clearHistoryMutation.isPending}
              onClick={() => {
                clearHistoryMutation.mutate(undefined, {
                  onSuccess: () => setConfirmClearHistory(false),
                })
              }}
            >
              {t('tasks.clearHistory')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppShell>
  )
}
