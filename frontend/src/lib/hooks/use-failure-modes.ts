import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { failureModesApi } from '@/lib/api/failure-modes'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import { CreateFailureModeRequest, UpdateFailureModeRequest } from '@/lib/types/api'

export function useFailureModes() {
  return useQuery({
    queryKey: QUERY_KEYS.failureModes,
    queryFn: () => failureModesApi.list({ order_by: 'updated desc' }),
  })
}

export function useFailureMode(id: string) {
  return useQuery({
    queryKey: QUERY_KEYS.failureMode(id),
    queryFn: () => failureModesApi.get(id),
    enabled: !!id,
  })
}

export function useCreateFailureMode() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (data: CreateFailureModeRequest) => failureModesApi.create(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.failureModes })
      toast({
        title: t('common.success'),
        description: t('failureModes.createSuccess'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}

export function useUpdateFailureMode() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateFailureModeRequest }) =>
      failureModesApi.update(id, data),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.failureModes })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.failureMode(id) })
      toast({
        title: t('common.success'),
        description: t('failureModes.updateSuccess'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}

export function useDeleteFailureMode() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: (id: string) => failureModesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.failureModes })
      toast({
        title: t('common.success'),
        description: t('failureModes.deleteSuccess'),
      })
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}

export function useImportFailureModes() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) =>
      failureModesApi.importFailureModes(file, dryRun),
    onSuccess: (preview, { dryRun }) => {
      // Only the confirmed import changes data; previews leave caches alone.
      if (!dryRun) {
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.failureModes })
        toast({
          title: t('common.success'),
          description: t('failureModes.importSuccess', { count: preview.imported_count }),
        })
      }
    },
    onError: (error: unknown) => {
      toast({
        title: t('common.error'),
        description: t(getApiErrorKey(error, t('common.error'))),
        variant: 'destructive',
      })
    },
  })
}
