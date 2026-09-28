import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { tasksApi, isActiveTask } from '@/lib/api/tasks'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'

export function useTasks(limit = 50) {
  return useQuery({
    queryKey: QUERY_KEYS.tasks(limit),
    queryFn: () => tasksApi.list(limit),
    // Poll every 2s while any job is active (mirrors useSourceStatus);
    // stop polling once every job reached a terminal state.
    refetchInterval: (query) => {
      const tasks = query.state.data
      if (Array.isArray(tasks) && tasks.some((task) => isActiveTask(task))) {
        return 2000
      }
      return false
    },
    staleTime: 0, // Always consider task state stale for real-time updates
  })
}

export function useDeleteTask() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (jobId: string) => tasksApi.deleteTask(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      toast({
        title: t('common.success'),
        description: t('tasks.deleteSuccess'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('tasks.deleteFailed'))),
        variant: 'destructive',
      })
    },
  })
}
