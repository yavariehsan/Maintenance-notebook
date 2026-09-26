import apiClient from './client'

/**
 * Frontend client for the repair-report collection API
 * (`/api/repair-reports/...`, Milestone 6).
 *
 * Repair reports are raw uploaded workbooks plus their analysis states;
 * the precomputed troubleshooting knowledge itself stays behind the
 * read-only troubleshooting client (`./troubleshooting.ts`), which this
 * module never duplicates. No filesystem paths ever appear here.
 */

export type RepairReportAnalysisState =
  | 'not_analyzed'
  | 'queued'
  | 'processing'
  | 'completed'
  | 'failed'

export type RepairAnalysisRunStatus =
  | 'queued'
  | 'processing'
  | 'completed'
  | 'failed'

export interface RepairReport {
  id: string
  filename: string
  size_bytes: number | null
  sheet: string | null
  column_count: number | null
  data_rows: number | null
  analysis_state: RepairReportAnalysisState
  last_run_id: string | null
  last_error: string | null
  created: string | null
  updated: string | null
}

export interface RepairAnalysisRunManifestEntry {
  report_id: string
  filename: string | null
  analysis_key: string | null
  source_sheet: string | null
  aggregate_sheet: string | null
  first_row: number | null
  last_row: number | null
  row_count: number | null
}

export interface RepairAnalysisRun {
  id: string
  report_ids: string[]
  manifest: RepairAnalysisRunManifestEntry[]
  status: RepairAnalysisRunStatus
  command_id: string | null
  error: string | null
  record_count: number | null
  equipment_count: number | null
  failure_mode_count: number | null
  guide_count: number | null
  created: string | null
  started_at: string | null
  finished_at: string | null
}

export interface RepairReportDetail {
  report: RepairReport
  last_run: RepairAnalysisRun | null
}

export interface RepairReportPreview {
  sheet: string
  columns: string[]
  rows: (string | number | boolean | null)[][]
  total_data_rows: number
  truncated: boolean
}

export interface StartAnalysisResult {
  run: RepairAnalysisRun
  message: string
}

/** Reports whose analysis state may still change (keep polling). */
export function isActiveRepairReport(report: RepairReport): boolean {
  return report.analysis_state === 'queued' || report.analysis_state === 'processing'
}

function reportPath(id: string): string {
  return `/repair-reports/${encodeURIComponent(id)}`
}

export const repairReportsApi = {
  upload: async (file: File): Promise<RepairReport> => {
    const formData = new FormData()
    formData.append('file', file)
    const response = await apiClient.post<RepairReport>('/repair-reports', formData)
    return response.data
  },

  list: async (): Promise<RepairReport[]> => {
    const response = await apiClient.get<RepairReport[]>('/repair-reports')
    return response.data
  },

  get: async (id: string): Promise<RepairReportDetail> => {
    const response = await apiClient.get<RepairReportDetail>(reportPath(id))
    return response.data
  },

  preview: async (id: string): Promise<RepairReportPreview> => {
    const response = await apiClient.get<RepairReportPreview>(`${reportPath(id)}/preview`)
    return response.data
  },

  startAnalysis: async (): Promise<StartAnalysisResult> => {
    const response = await apiClient.post<StartAnalysisResult>('/repair-reports/analyze')
    return response.data
  },

  listRuns: async (): Promise<RepairAnalysisRun[]> => {
    const response = await apiClient.get<RepairAnalysisRun[]>('/repair-reports/runs')
    return response.data
  },
}
