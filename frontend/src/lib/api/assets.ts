import apiClient from './client'
import {
  AssetResponse,
  CreateAssetRequest,
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
}
