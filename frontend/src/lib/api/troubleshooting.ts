import apiClient from './client'

/**
 * Read-only frontend client for the troubleshooting runtime API
 * (`GET /api/troubleshooting/...`, established in Milestone 4).
 *
 * Types mirror the backend Pydantic response models 1:1 — no invented
 * fields, no score conversions. Support/probability/confidence values
 * are passed through exactly as precomputed by the offline pipeline.
 * There are intentionally no POST/PUT/PATCH/DELETE operations here.
 */

export type TroubleshootingDatabaseState =
  | 'available'
  | 'missing'
  | 'unreadable'
  | 'incompatible'
  | 'unavailable'

export interface TroubleshootingStatus {
  state: TroubleshootingDatabaseState
  schema_version: string | null
  expected_schema_version: string | null
  equipment_count: number | null
  message: string
}

export interface TroubleshootingEquipment {
  code: string
  name: string | null
  manufacturer: string | null
  model: string | null
  record_count: number
  failure_mode_count: number
}

export interface TroubleshootingFailureMode {
  id: string
  label: string
  record_count: number
  cause_count: number
}

export interface TroubleshootingCauseAction {
  id: string | null
  category: string | null
  role: string | null
  action_text: string | null
  source_record_ids: string[]
  frequency: number | null
}

export interface TroubleshootingCauseEvidence {
  id: string | null
  record_id: string | null
  equipment_code: string | null
  relevance_basis: string | null
  relevance_detail: string | null
  weight: number | null
  symptom_text: string | null
  repair_description: string | null
}

export interface TroubleshootingCause {
  id: string
  label: string
  kinds: string[]
  /** Share of weighted scope evidence (not a probability). */
  support_percent: number | null
  evidence_count: number
  weighted_evidence: number
  denominator: number
  calculation_method: string
  similarity_score: number | null
  similarity_basis: string | null
  confidence: number | null
  /** Normalized share of evidence weight across causes. */
  probability: number | null
  rank: number
  actions: TroubleshootingCauseAction[]
  evidence: TroubleshootingCauseEvidence[]
}

export interface TroubleshootingSection {
  section: string | null
  title: string | null
  position: number | null
  body: string | null
}

export interface TroubleshootingSafetyNote {
  note_text: string | null
  source_record_ids: string[]
  cause_ids: string[]
}

export interface TroubleshootingGuide {
  equipment_code: string
  failure_mode_id: string
  failure_mode_label: string
  symptom_summary: string
  causes: TroubleshootingCause[]
  sections: TroubleshootingSection[]
  safety_notes: TroubleshootingSafetyNote[]
  warnings: string[]
}

/**
 * Machine-readable availability gate for consuming components: only the
 * `available` state means knowledge reads can succeed. Every other state
 * (`missing` | `unreadable` | `incompatible` | `unavailable`) must be
 * surfaced distinctly by the future UI, never collapsed into "no data".
 */
export function isTroubleshootingAvailable(
  status: TroubleshootingStatus | null | undefined,
): boolean {
  return status?.state === 'available'
}

function equipmentPath(code: string): string {
  return `/troubleshooting/equipment/${encodeURIComponent(code)}`
}

function modePath(code: string, modeId: string): string {
  return `${equipmentPath(code)}/failure-modes/${encodeURIComponent(modeId)}`
}

export const troubleshootingApi = {
  getStatus: async (): Promise<TroubleshootingStatus> => {
    const response = await apiClient.get<TroubleshootingStatus>(
      '/troubleshooting/status',
    )
    return response.data
  },

  listEquipment: async (): Promise<TroubleshootingEquipment[]> => {
    const response = await apiClient.get<TroubleshootingEquipment[]>(
      '/troubleshooting/equipment',
    )
    return response.data
  },

  getEquipment: async (code: string): Promise<TroubleshootingEquipment> => {
    const response = await apiClient.get<TroubleshootingEquipment>(
      equipmentPath(code),
    )
    return response.data
  },

  listFailureModes: async (
    code: string,
  ): Promise<TroubleshootingFailureMode[]> => {
    const response = await apiClient.get<TroubleshootingFailureMode[]>(
      `${equipmentPath(code)}/failure-modes`,
    )
    return response.data
  },

  getGuide: async (
    code: string,
    modeId: string,
  ): Promise<TroubleshootingGuide> => {
    const response = await apiClient.get<TroubleshootingGuide>(
      modePath(code, modeId),
    )
    return response.data
  },

  listCauses: async (
    code: string,
    modeId: string,
  ): Promise<TroubleshootingCause[]> => {
    const response = await apiClient.get<TroubleshootingCause[]>(
      `${modePath(code, modeId)}/causes`,
    )
    return response.data
  },

  listEvidence: async (
    code: string,
    modeId: string,
  ): Promise<TroubleshootingCauseEvidence[]> => {
    const response = await apiClient.get<TroubleshootingCauseEvidence[]>(
      `${modePath(code, modeId)}/evidence`,
    )
    return response.data
  },
}
