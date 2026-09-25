import { describe, it, expect, vi, beforeEach } from 'vitest'

import apiClient from '@/lib/api/client'
import { troubleshootingApi, isTroubleshootingAvailable } from './troubleshooting'

// useTranslation is mocked globally in setup.ts (t returns the key string)

vi.mock('@/lib/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

const getMock = vi.mocked(apiClient.get)
const postMock = vi.mocked(apiClient.post)
const putMock = vi.mocked(apiClient.put)
const patchMock = vi.mocked(apiClient.patch)
const deleteMock = vi.mocked(apiClient.delete)

describe('troubleshootingApi endpoints', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls the exact backend routes with encoded path parameters', async () => {
    getMock.mockResolvedValue({ data: null })
    await troubleshootingApi.getStatus()
    await troubleshootingApi.listEquipment()
    await troubleshootingApi.getEquipment('B104')
    await troubleshootingApi.listFailureModes('B104')
    await troubleshootingApi.getGuide('B104', 'FM-0001')
    await troubleshootingApi.listCauses('B104', 'FM-0001')
    await troubleshootingApi.listEvidence('B104', 'FM-0001')

    const urls = getMock.mock.calls.map((call) => call[0])
    expect(urls).toEqual([
      '/troubleshooting/status',
      '/troubleshooting/equipment',
      '/troubleshooting/equipment/B104',
      '/troubleshooting/equipment/B104/failure-modes',
      '/troubleshooting/equipment/B104/failure-modes/FM-0001',
      '/troubleshooting/equipment/B104/failure-modes/FM-0001/causes',
      '/troubleshooting/equipment/B104/failure-modes/FM-0001/evidence',
    ])
  })

  it('URL-encodes identifiers that need it', async () => {
    getMock.mockResolvedValue({ data: null })
    await troubleshootingApi.getEquipment('B 104/X')
    expect(getMock).toHaveBeenCalledWith(
      '/troubleshooting/equipment/B%20104%2FX',
    )
  })

  it('returns the response payload unchanged (provenance preserved)', async () => {
    const guide = {
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
          evidence_count: 3,
          weighted_evidence: 2.5,
          denominator: 4.0,
          calculation_method: 'similarity-weighted-share-v1',
          similarity_score: 1.0,
          similarity_basis: 'same_equipment_code+same_failure_mode',
          confidence: 0.6,
          probability: 0.625,
          rank: 1,
          actions: [],
          evidence: [{ id: 'ev-1', record_id: 'B-101' }],
        },
      ],
      sections: [],
      safety_notes: [],
      warnings: [],
    }
    getMock.mockResolvedValue({ data: guide })
    const result = await troubleshootingApi.getGuide('B104', 'FM-0001')
    expect(result).toEqual(guide)
    // Precomputed values pass through untouched — no frontend rescoring.
    expect(result.causes[0].support_percent).toBe(62.5)
    expect(result.causes[0].probability).toBe(0.625)
    expect(result.causes[0].evidence[0].record_id).toBe('B-101')
  })

  it('propagates API errors to the caller', async () => {
    const failure = new Error('Request failed with status code 503')
    getMock.mockRejectedValue(failure)
    await expect(troubleshootingApi.listEquipment()).rejects.toBe(failure)
  })

  it('exposes read operations only (no mutations at the HTTP boundary)', async () => {
    getMock.mockResolvedValue({ data: null })
    await troubleshootingApi.getStatus()
    await troubleshootingApi.listEquipment()
    await troubleshootingApi.getEquipment('B104')
    await troubleshootingApi.listFailureModes('B104')
    await troubleshootingApi.getGuide('B104', 'FM-0001')
    await troubleshootingApi.listCauses('B104', 'FM-0001')
    await troubleshootingApi.listEvidence('B104', 'FM-0001')

    expect(getMock).toHaveBeenCalledTimes(7)
    expect(postMock).not.toHaveBeenCalled()
    expect(putMock).not.toHaveBeenCalled()
    expect(patchMock).not.toHaveBeenCalled()
    expect(deleteMock).not.toHaveBeenCalled()
    expect(Object.keys(troubleshootingApi).sort()).toEqual(
      [
        'getEquipment',
        'getGuide',
        'getStatus',
        'listCauses',
        'listEquipment',
        'listEvidence',
        'listFailureModes',
      ].sort(),
    )
  })
})

describe('isTroubleshootingAvailable', () => {
  it.each([
    ['available', true],
    ['missing', false],
    ['unreadable', false],
    ['incompatible', false],
    ['unavailable', false],
  ])('state %s → %s', (state, expected) => {
    expect(
      isTroubleshootingAvailable({
        state: state as 'available',
        schema_version: null,
        expected_schema_version: '1',
        equipment_count: null,
        message: state,
      }),
    ).toBe(expected)
  })

  it('treats absent status as unavailable', () => {
    expect(isTroubleshootingAvailable(null)).toBe(false)
    expect(isTroubleshootingAvailable(undefined)).toBe(false)
  })
})
