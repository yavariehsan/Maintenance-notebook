import apiClient from './client'

/**
 * Frontend client for LLM troubleshooting knowledge (`/api/repair-reports/llm-builds/...`
 * and `/api/troubleshooting/llm/guide`, M12).
 *
 * Second, independent knowledge source beside deterministic text mining:
 * builds coexist, every record carries its stable source IDs plus
 * DATA_SUPPORTED vs LLM_INFERRED provenance. No filesystem paths here.
 */

export type LLMBuildStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'partial'
  | 'failed'
  | 'cancelled'

export interface LLMBuildManifestEntry {
  report_id: string
  filename: string | null
  analysis_key: string | null
}

export interface LLMKnowledgeBuild {
  id: string
  source_report_ids: string[]
  manifest: LLMBuildManifestEntry[]
  status: LLMBuildStatus
  command_id: string | null
  model: string | null
  prompt_version: string | null
  error: string | null
  warnings: string[]
  record_count: number | null
  failed_record_count: number | null
  created: string | null
  started_at: string | null
  finished_at: string | null
}

export type LLMItemBasis = 'DATA_SUPPORTED' | 'LLM_INFERRED'

export interface LLMKnowledgeItem {
  text: string | null
  basis: LLMItemBasis | null
  source_quote: string | null
}

export interface LLMKnowledgeRecord {
  id: string | null
  build_id: string | null
  source_report_id: string | null
  source_record_id: string | null
  source_text: string | null
  symptom: string | null
  findings: LLMKnowledgeItem[]
  candidate_causes: LLMKnowledgeItem[]
  diagnostic_steps: LLMKnowledgeItem[]
  corrective_actions: LLMKnowledgeItem[]
  verification_steps: LLMKnowledgeItem[]
  post_repair_events: LLMKnowledgeItem[]
  record_error: string | null
  created: string | null
}

export interface LLMGuide {
  knowledge_source: 'LLM'
  build_id: string
  model: string | null
  prompt_version: string | null
  source_report_id: string
  source_filename: string | null
  source_deleted: boolean
  records: LLMKnowledgeRecord[]
  warnings: string[]
}

export function isActiveLLMBuild(build: LLMKnowledgeBuild): boolean {
  return build.status === 'queued' || build.status === 'running'
}

export const llmKnowledgeApi = {
  listBuilds: async (): Promise<LLMKnowledgeBuild[]> => {
    const response = await apiClient.get<LLMKnowledgeBuild[]>('/repair-reports/llm-builds')
    return response.data
  },

  getBuild: async (buildId: string): Promise<LLMKnowledgeBuild> => {
    const response = await apiClient.get<LLMKnowledgeBuild>(
      `/repair-reports/llm-builds/${encodeURIComponent(buildId)}`,
    )
    return response.data
  },

  startBuild: async (reportIds: string[]): Promise<LLMKnowledgeBuild> => {
    const response = await apiClient.post<{ build: LLMKnowledgeBuild }>(
      '/repair-reports/llm-builds',
      { report_ids: reportIds },
    )
    return response.data.build
  },

  listRecords: async (
    buildId: string,
    sourceReportId?: string,
  ): Promise<LLMKnowledgeRecord[]> => {
    const response = await apiClient.get<LLMKnowledgeRecord[]>(
      `/repair-reports/llm-builds/${encodeURIComponent(buildId)}/records`,
      sourceReportId ? { params: { source_report_id: sourceReportId } } : undefined,
    )
    return response.data
  },

  getGuide: async (buildId: string, sourceReportId: string): Promise<LLMGuide> => {
    const response = await apiClient.get<LLMGuide>('/troubleshooting/llm/guide', {
      params: { build_id: buildId, source_report_id: sourceReportId },
    })
    return response.data
  },
}
