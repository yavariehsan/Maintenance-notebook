import { describe, it, expect, vi, beforeEach } from 'vitest'

import apiClient from '@/lib/api/client'
import { QUERY_KEYS } from '@/lib/api/query-client'
import { repairReportsApi, isActiveRepairReport } from './repair-reports'
import type { RepairReport } from './repair-reports'

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

const report = (state: RepairReport['analysis_state']): RepairReport => ({
  id: 'repair_report:abc',
  filename: 'cmms.xlsx',
  size_bytes: 10,
  sheet: 'Sheet1',
  column_count: 9,
  data_rows: 4,
  analysis_state: state,
  last_run_id: null,
  last_error: null,
  created: null,
  updated: null,
})

describe('repairReportsApi endpoints', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls the exact backend routes with encoded identifiers', async () => {
    getMock.mockResolvedValue({ data: null })
    postMock.mockResolvedValue({ data: null })
    await repairReportsApi.list()
    await repairReportsApi.get('repair_report:abc')
    await repairReportsApi.preview('repair_report:abc')
    await repairReportsApi.startAnalysis()
    await repairReportsApi.startSingleReportAnalysis('repair_report:abc')
    await repairReportsApi.getActions('repair_report:abc')
    await repairReportsApi.listRuns()

    expect(getMock.mock.calls.map((call) => call[0])).toEqual([
      '/repair-reports',
      '/repair-reports/repair_report%3Aabc',
      '/repair-reports/repair_report%3Aabc/preview',
      '/repair-reports/repair_report%3Aabc/actions',
      '/repair-reports/runs',
    ])
    expect(postMock.mock.calls.map((call) => call[0])).toEqual([
      '/repair-reports/analyze',
      '/repair-reports/repair_report%3Aabc/analyze',
    ])
  })

  it('uploads via multipart FormData without inventing fields', async () => {
    postMock.mockResolvedValue({ data: null })
    const file = new File(['x'], 'cmms.xlsx')
    await repairReportsApi.upload(file)
    expect(postMock).toHaveBeenCalledWith(
      '/repair-reports',
      expect.any(FormData),
    )
    const formData = postMock.mock.calls[0][1] as FormData
    expect(formData.get('file')).toBe(file)
  })

  it('uses stable hierarchical query keys', () => {
    expect(QUERY_KEYS.repairReports).toEqual(['repair-reports'])
    expect(QUERY_KEYS.repairReport('repair_report:abc')).toEqual([
      'repair-reports',
      'repair_report:abc',
    ])
    expect(QUERY_KEYS.repairReportPreview('repair_report:abc')).toEqual([
      'repair-reports',
      'repair_report:abc',
      'preview',
    ])
    expect(QUERY_KEYS.repairReportActions('repair_report:abc')).toEqual([
      'repair-reports',
      'repair_report:abc',
      'actions',
    ])
    expect(QUERY_KEYS.repairAnalysisRuns).toEqual(['repair-reports', 'runs'])
  })
})

describe('isActiveRepairReport', () => {
  it('polls only while queued or processing', () => {
    expect(isActiveRepairReport(report('queued'))).toBe(true)
    expect(isActiveRepairReport(report('processing'))).toBe(true)
    expect(isActiveRepairReport(report('not_analyzed'))).toBe(false)
    expect(isActiveRepairReport(report('completed'))).toBe(false)
    expect(isActiveRepairReport(report('failed'))).toBe(false)
  })
})
