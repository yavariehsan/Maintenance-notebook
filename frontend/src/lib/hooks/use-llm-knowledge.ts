import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { isActiveLLMBuild, llmKnowledgeApi } from '@/lib/api/llm-knowledge'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'

/**
 * TanStack Query hooks for LLM troubleshooting knowledge (M12).
 *
 * Build-list queries poll every 2s while any visible build is queued or
 * running (same convention as repair reports) and go quiet at terminal
 * states. Mutations invalidate build caches and wake the Tasks page.
 */

export function useLLMBuilds() {
  return useQuery({
    queryKey: QUERY_KEYS.llmBuilds,
    queryFn: () => llmKnowledgeApi.listBuilds(),
    refetchInterval: (query) => {
      const builds = query.state.data
      if (Array.isArray(builds) && builds.some(isActiveLLMBuild)) {
        return 2000
      }
      return false
    },
    staleTime: 0,
  })
}

export function useLLMBuild(buildId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.llmBuild(buildId ?? ''),
    queryFn: () => llmKnowledgeApi.getBuild(buildId ?? ''),
    enabled: !!buildId,
    refetchInterval: (query) => {
      const build = query.state.data
      if (build && isActiveLLMBuild(build)) {
        return 2000
      }
      return false
    },
    staleTime: 0,
  })
}

export function useLLMGuide(buildId: string | null, sourceReportId: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.llmGuide(buildId ?? '', sourceReportId ?? ''),
    queryFn: () => llmKnowledgeApi.getGuide(buildId ?? '', sourceReportId ?? ''),
    enabled: !!buildId && !!sourceReportId,
    staleTime: 0,
  })
}

export function useStartLLMBuild() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (reportIds: string[]) => llmKnowledgeApi.startBuild(reportIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.llmBuilds })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.repairReports })
      // Wake the Tasks page so the fresh build command is visible.
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      toast({
        title: t('common.success'),
        description: t('llmKnowledge.buildStarted'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('llmKnowledge.buildFailed'))),
        variant: 'destructive',
      })
    },
  })
}
