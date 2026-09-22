import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { assetsApi } from '@/lib/api/assets'
import { maintenanceApi } from '@/lib/api/maintenance'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import { getApiErrorKey } from '@/lib/utils/error-handler'
import type { MaintenanceAskRequest } from '@/lib/types/api'

export function useMaintenanceSources(equipmentCode: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.maintenanceSources(equipmentCode ?? ''),
    queryFn: () => maintenanceApi.listSources(equipmentCode as string),
    enabled: !!equipmentCode,
  })
}

export function useMaintenanceAsk() {
  return useMutation({
    mutationFn: (data: MaintenanceAskRequest) => maintenanceApi.ask(data),
  })
}

export function useImportEquipment() {
  const queryClient = useQueryClient()
  const { toast } = useToast()
  const { t } = useTranslation()

  return useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) =>
      assetsApi.importEquipment(file, dryRun),
    onSuccess: (preview, { dryRun }) => {
      // Only the confirmed import changes data; previews leave caches alone.
      if (!dryRun) {
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.assets })
        toast({
          title: t('common.success'),
          description: t('assets.importSuccess', { count: preview.imported_count }),
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
