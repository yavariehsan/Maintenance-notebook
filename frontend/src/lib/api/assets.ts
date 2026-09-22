import apiClient from './client'
import {
  AssetResponse,
  CreateAssetRequest,
  EquipmentImportPreview,
  UpdateAssetRequest,
} from '@/lib/types/api'

export const assetsApi = {
  list: async (params?: { order_by?: string }) => {
    const response = await apiClient.get<AssetResponse[]>('/assets', { params })
    return response.data
  },

  get: async (id: string) => {
    const response = await apiClient.get<AssetResponse>(`/assets/${id}`)
    return response.data
  },

  getByCode: async (code: string) => {
    const response = await apiClient.get<AssetResponse>(
      `/assets/by-code/${encodeURIComponent(code)}`
    )
    return response.data
  },

  create: async (data: CreateAssetRequest) => {
    const response = await apiClient.post<AssetResponse>('/assets', data)
    return response.data
  },

  update: async (id: string, data: UpdateAssetRequest) => {
    const response = await apiClient.put<AssetResponse>(`/assets/${id}`, data)
    return response.data
  },

  delete: async (id: string) => {
    const response = await apiClient.delete<{ message: string }>(`/assets/${id}`)
    return response.data
  },

  importEquipment: async (file: File, dryRun: boolean) => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await apiClient.post<EquipmentImportPreview>(
      '/assets/import',
      formData,
      { params: { dry_run: dryRun } }
    )
    return response.data
  },
}
