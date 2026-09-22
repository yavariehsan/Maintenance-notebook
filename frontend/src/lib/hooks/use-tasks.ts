import { useQuery } from '@tanstack/react-query'
import { tasksApi, isActiveTask } from '@/lib/api/tasks'
import { QUERY_KEYS } from '@/lib/api/query-client'

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
