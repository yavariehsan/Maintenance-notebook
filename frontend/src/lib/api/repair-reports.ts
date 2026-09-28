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

export interface ReportRepairAction {
  id: string | null
  category: string | null
  role: string | null
  action_text: string | null
  source_record_ids: string[]
  frequency: number | null
}

export interface ReportVerification {
  id: string | null
  record_id: string | null
  sentence: string | null
  event_type: string | null
  repair_action_id: string | null
}

export interface ReportPostRepairEvent {
  id: string | null
  record_id: string | null
  sentence: string | null
  event_type: string | null
  repair_action_id: string | null
}

export interface ReportActions {
  report_id: string
  analysis_key: string
  run_id: string | null
  record_ids: string[]
  repair_actions: ReportRepairAction[]
  verifications: ReportVerification[]
  post_repair_events: ReportPostRepairEvent[]
  history_only_record_ids: string[]
  warnings: string[]
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

  startSingleReportAnalysis: async (id: string): Promise<StartAnalysisResult> => {
    const response = await apiClient.post<StartAnalysisResult>(`${reportPath(id)}/analyze`)
    return response.data
  },

  getActions: async (id: string): Promise<ReportActions> => {
    const response = await apiClient.get<ReportActions>(`${reportPath(id)}/actions`)
    return response.data
  },

  listRuns: async (): Promise<RepairAnalysisRun[]> => {
    const response = await apiClient.get<RepairAnalysisRun[]>('/repair-reports/runs')
    return response.data
  },
}
