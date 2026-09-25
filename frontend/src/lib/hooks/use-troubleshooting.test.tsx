import React from 'react'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { QUERY_KEYS } from '@/lib/api/query-client'
import { troubleshootingApi } from '@/lib/api/troubleshooting'
import type {
  TroubleshootingDatabaseState,
  TroubleshootingEquipment,
  TroubleshootingGuide,
} from '@/lib/api/troubleshooting'
import {
  useTroubleshootingCauses,
  useTroubleshootingEquipment,
  useTroubleshootingEquipmentDetail,
  useTroubleshootingEvidence,
  useTroubleshootingFailureModes,
  useTroubleshootingGuide,
  useTroubleshootingStatus,
} from './use-troubleshooting'

// useTranslation is mocked globally in setup.ts (t returns the key string)

vi.mock('@/lib/api/troubleshooting', () => ({
  troubleshootingApi: {
    getStatus: vi.fn(),
    listEquipment: vi.fn(),
    getEquipment: vi.fn(),
    listFailureModes: vi.fn(),
    getGuide: vi.fn(),
    listCauses: vi.fn(),
    listEvidence: vi.fn(),
  },
  isTroubleshootingAvailable: vi.fn((status) => status?.state === 'available'),
}))

const api = vi.mocked(troubleshootingApi, true)

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const statusAvailable = {
  state: 'available',
  schema_version: '1',
  expected_schema_version: '1',
  equipment_count: 2,
  message: 'ok',
}

describe('use-troubleshooting query keys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses stable hierarchical keys matching the API routes', () => {
    expect(QUERY_KEYS.troubleshootingStatus).toEqual(['troubleshooting', 'status'])
    expect(QUERY_KEYS.troubleshootingEquipment).toEqual(['troubleshooting', 'equipment'])
    expect(QUERY_KEYS.troubleshootingEquipmentDetail('B104')).toEqual([
      'troubleshooting',
      'equipment',
      'B104',
    ])
    expect(QUERY_KEYS.troubleshootingFailureModes('B104')).toEqual([
      'troubleshooting',
      'equipment',
      'B104',
      'failure-modes',
    ])
    expect(QUERY_KEYS.troubleshootingGuide('B104', 'FM-0001')).toEqual([
      'troubleshooting',
      'equipment',
      'B104',
      'failure-modes',
      'FM-0001',
    ])
    expect(QUERY_KEYS.troubleshootingCauses('B104', 'FM-0001')).toEqual([
      'troubleshooting',
      'equipment',
      'B104',
      'failure-modes',
      'FM-0001',
      'causes',
    ])
    expect(QUERY_KEYS.troubleshootingEvidence('B104', 'FM-0001')).toEqual([
      'troubleshooting',
      'equipment',
      'B104',
      'failure-modes',
      'FM-0001',
      'evidence',
    ])
  })
})

describe('use-troubleshooting dependent queries stay disabled', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it.each([
    ['equipment detail without code', () =>
      renderHook(() => useTroubleshootingEquipmentDetail(null), {
        wrapper: makeWrapper(),
      }),
    'getEquipment'],
    ['failure modes without code', () =>
      renderHook(() => useTroubleshootingFailureModes(null), {
        wrapper: makeWrapper(),
      }),
    'listFailureModes'],
    ['guide without scope', () =>
      renderHook(() => useTroubleshootingGuide(null, null), {
        wrapper: makeWrapper(),
      }),
    'getGuide'],
    ['guide with code but no mode', () =>
      renderHook(() => useTroubleshootingGuide('B104', null), {
        wrapper: makeWrapper(),
      }),
    'getGuide'],
    ['causes without scope', () =>
      renderHook(() => useTroubleshootingCauses('B104', null), {
        wrapper: makeWrapper(),
      }),
    'listCauses'],
    ['evidence without scope', () =>
      renderHook(() => useTroubleshootingEvidence(null, 'FM-0001'), {
        wrapper: makeWrapper(),
      }),
    'listEvidence'],
  ])('%s: does not fetch', (_label, render, method) => {
    const { result } = render()
    expect(result.current.isPending).toBe(true)
    expect(result.current.fetchStatus).toBe('idle')
    expect(api[method as keyof typeof api]).not.toHaveBeenCalled()
  })
})

describe('use-troubleshooting responses', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns equipment on success', async () => {
    const equipment: TroubleshootingEquipment[] = [
      {
        code: 'B104',
        name: 'mill',
        manufacturer: 'STARRAG',
        model: 'SX-1',
        record_count: 3,
        failure_mode_count: 2,
      },
    ]
    api.listEquipment.mockResolvedValue(equipment)
    const { result } = renderHook(() => useTroubleshootingEquipment(), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(equipment)
  })

  it('distinguishes empty results from loading and error', async () => {
    api.listFailureModes.mockResolvedValue([])
    const { result } = renderHook(() => useTroubleshootingFailureModes('B104'), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([])
    expect(result.current.isError).toBe(false)
  })

  it('surfaces API errors without retrying blindly in the hook', async () => {
    api.getGuide.mockRejectedValue(new Error('boom'))
    const { result } = renderHook(() => useTroubleshootingGuide('B104', 'FM-0001'), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeInstanceOf(Error)
  })

  it('passes status variants through for the UI to distinguish', async () => {
    const states: TroubleshootingDatabaseState[] = [
      'available',
      'missing',
      'unreadable',
      'incompatible',
      'unavailable',
    ]
    for (const state of states) {
      api.getStatus.mockResolvedValue({ ...statusAvailable, state })
      const { result } = renderHook(() => useTroubleshootingStatus(), {
        wrapper: makeWrapper(),
      })
      await waitFor(() => expect(result.current.isSuccess).toBe(true))
      expect(result.current.data?.state).toBe(state)
    }
  })

  it('returns guides with provenance intact', async () => {
    const guide: TroubleshootingGuide = {
      equipment_code: 'B104',
      failure_mode_id: 'FM-0001',
      failure_mode_label: 'label',
      symptom_summary: 'summary',
      causes: [
        {
          id: 'cause-1',
          label: 'cause',
          kinds: ['explicitly_recorded'],
          support_percent: 62.5,
          evidence_count: 1,
          weighted_evidence: 1.0,
          denominator: 1.6,
          calculation_method: 'similarity-weighted-share-v1',
          similarity_score: 1.0,
          similarity_basis: 'same_equipment_code+same_failure_mode',
          confidence: 0.6,
          probability: 0.625,
          rank: 1,
          actions: [],
          evidence: [
            {
              id: 'ev-1',
              record_id: 'B-101',
              equipment_code: 'B104',
              relevance_basis: 'exact_equipment',
              relevance_detail: 'same_equipment_code+same_failure_mode',
              weight: 1.0,
              symptom_text: 'symptom',
              repair_description: 'repair',
            },
          ],
        },
      ],
      sections: [],
      safety_notes: [],
      warnings: ['insufficient_historical_repair_evidence'],
    }
    api.getGuide.mockResolvedValue(guide)
    const { result } = renderHook(() => useTroubleshootingGuide('B104', 'FM-0001'), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const cause = result.current.data?.causes[0]
    expect(cause?.support_percent).toBe(62.5)
    expect(cause?.probability).toBe(0.625)
    expect(cause?.confidence).toBe(0.6)
    expect(cause?.evidence[0].record_id).toBe('B-101')
    expect(result.current.data?.warnings).toContain(
      'insufficient_historical_repair_evidence',
    )
  })
})
