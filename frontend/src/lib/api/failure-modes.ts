import apiClient from './client'
import {
  CreateFailureModeRequest,
  FailureModeImportPreview,
  FailureModeResponse,
  UpdateFailureModeRequest,
} from '@/lib/types/api'

export const failureModesApi = {
  list: async (params?: { order_by?: string }) => {
    const response = await apiClient.get<FailureModeResponse[]>('/failure-modes', { params })
    return response.data
  },

  get: async (id: string) => {
    const response = await apiClient.get<FailureModeResponse>(`/failure-modes/${id}`)
    return response.data
  },

  create: async (data: CreateFailureModeRequest) => {
    const response = await apiClient.post<FailureModeResponse>('/failure-modes', data)
    return response.data
  },

  update: async (id: string, data: UpdateFailureModeRequest) => {
    const response = await apiClient.put<FailureModeResponse>(`/failure-modes/${id}`, data)
    return response.data
  },

  delete: async (id: string) => {
    const response = await apiClient.delete<{ message: string }>(`/failure-modes/${id}`)
    return response.data
  },

  importFailureModes: async (file: File, dryRun: boolean) => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await apiClient.post<FailureModeImportPreview>(
      '/failure-modes/import',
      formData,
      { params: { dry_run: dryRun } }
    )
    return response.data
  },
}
