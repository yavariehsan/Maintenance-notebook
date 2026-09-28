import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { repairReportsApi, isActiveRepairReport } from '@/lib/api/repair-reports'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'

/**
 * TanStack Query hooks for the repair-report collection.
 *
 * List/detail queries poll every 2s while any visible report is queued or
 * processing (same convention as useTasks/useSourceStatus) and go quiet
 * once every report reaches a terminal state. Mutations invalidate the
 * report caches and surface localized toasts.
 */

export function useRepairReports() {
  return useQuery({
    queryKey: QUERY_KEYS.repairReports,
    queryFn: () => repairReportsApi.list(),
    refetchInterval: (query) => {
      const reports = query.state.data
      if (Array.isArray(reports) && reports.some(isActiveRepairReport)) {
        return 2000
      }
      return false
    },
    staleTime: 0,
  })
}

export function useRepairReport(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.repairReport(id),
    queryFn: () => repairReportsApi.get(id),
    enabled: !!id,
    refetchInterval: (query) => {
      const detail = query.state.data
      if (detail && isActiveRepairReport(detail.report)) {
        return 2000
      }
      return false
    },
    staleTime: 0,
  })
}

export function useRepairReportPreview(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.repairReportPreview(id),
    queryFn: () => repairReportsApi.preview(id),
    enabled: !!id,
  })
}

export function useRepairAnalysisRuns() {
  return useQuery({
    queryKey: QUERY_KEYS.repairAnalysisRuns,
    queryFn: () => repairReportsApi.listRuns(),
  })
}

export function useRepairReportActions(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.repairReportActions(id),
    queryFn: () => repairReportsApi.getActions(id),
    enabled: !!id,
    staleTime: 0,
  })
}

export function useUploadRepairReport() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (file: File) => repairReportsApi.upload(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.repairReports })
      toast({
        title: t('common.success'),
        description: t('repairReports.uploadSuccess'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('repairReports.uploadFailed'))),
        variant: 'destructive',
      })
    },
  })
}

export function useStartRepairAnalysis() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: () => repairReportsApi.startAnalysis(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.repairReports })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.repairAnalysisRuns })
      // Wake the Tasks page: its bounded polling is off while no job is
      // active, so a fresh analysis command would otherwise sit unseen.
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      toast({
        title: t('common.success'),
        description: t('repairReports.analyzeStarted'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('repairReports.analyzeFailed'))),
        variant: 'destructive',
      })
    },
  })
}

export function useStartSingleReportAnalysis(reportId: string) {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: () => repairReportsApi.startSingleReportAnalysis(reportId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.repairReports })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.repairReport(reportId) })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.repairAnalysisRuns })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      toast({
        title: t('common.success'),
        description: t('repairReports.analyzeStarted'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('repairReports.analyzeFailed'))),
        variant: 'destructive',
      })
    },
  })
}
