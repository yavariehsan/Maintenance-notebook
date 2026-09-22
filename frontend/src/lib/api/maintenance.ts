import apiClient from './client'
import {
  MaintenanceAskRequest,
  MaintenanceAskResponse,
  MaintenanceSourceRef,
} from '@/lib/types/api'

export const maintenanceApi = {
  listSources: async (equipmentCode: string) => {
    const response = await apiClient.get<MaintenanceSourceRef[]>(
      '/maintenance/sources',
      { params: { equipment_code: equipmentCode } }
    )
    return response.data
  },

  ask: async (data: MaintenanceAskRequest) => {
    const response = await apiClient.post<MaintenanceAskResponse>(
      '/maintenance/ask',
      data
    )
    return response.data
  },
}
