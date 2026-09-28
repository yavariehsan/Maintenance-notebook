import React from 'react'
import { renderHook, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { repairReportsApi } from '@/lib/api/repair-reports'
import { useStartRepairAnalysis, useStartSingleReportAnalysis } from './use-repair-reports'

vi.mock('@/lib/api/repair-reports', () => ({
  repairReportsApi: {
    upload: vi.fn(),
    list: vi.fn(),
    get: vi.fn(),
    preview: vi.fn(),
    startAnalysis: vi.fn(),
    startSingleReportAnalysis: vi.fn(),
    getActions: vi.fn(),
    listRuns: vi.fn(),
  },
  isActiveRepairReport: vi.fn(
    (report: { analysis_state: string }) =>
      report.analysis_state === 'queued' || report.analysis_state === 'processing',
  ),
}))

const api = vi.mocked(repairReportsApi, true)

function makeClient() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  const spy = vi.spyOn(client, 'invalidateQueries')
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return { Wrapper, spy }
}

describe('useStartRepairAnalysis cache sync', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('wakes report, run, and task caches when analysis starts', async () => {
    api.startAnalysis.mockResolvedValue({
      run: {
        id: 'repair_analysis_run:r1',
        report_ids: ['repair_report:abc'],
        manifest: [],
        status: 'queued',
        command_id: 'command:1',
        error: null,
        record_count: null,
        equipment_count: null,
        failure_mode_count: null,
        guide_count: null,
        created: null,
        started_at: null,
        finished_at: null,
      },
      message: 'ok',
    })
    const { Wrapper, spy } = makeClient()
    const { result } = renderHook(() => useStartRepairAnalysis(), {
      wrapper: Wrapper,
    })
    result.current.mutate()
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    // Reports + runs refresh so queued/processing appears immediately;
    // tasks refresh so the Tasks page picks up the new active command
    // even though its bounded polling was idle.
    expect(spy).toHaveBeenCalledWith({ queryKey: ['repair-reports'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['repair-reports', 'runs'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['tasks'] })
  })

  it('starts single-report runs without process-everything', async () => {
    api.startSingleReportAnalysis.mockResolvedValue({
      run: {
        id: 'repair_analysis_run:r1',
        report_ids: ['repair_report:abc'],
        manifest: [],
        status: 'queued',
        command_id: 'command:1',
        error: null,
        record_count: null,
        equipment_count: null,
        failure_mode_count: null,
        guide_count: null,
        created: null,
        started_at: null,
        finished_at: null,
      },
      message: 'ok',
    })
    const { Wrapper, spy } = makeClient()
    const { result } = renderHook(() => useStartSingleReportAnalysis('repair_report:abc'), {
      wrapper: Wrapper,
    })
    result.current.mutate()
    await waitFor(() => {
      expect(result.current.isSuccess).toBe(true)
    })
    expect(api.startSingleReportAnalysis).toHaveBeenCalledWith('repair_report:abc')
    expect(spy).toHaveBeenCalledWith({ queryKey: ['repair-reports', 'repair_report:abc'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['tasks'] })
  })
})
