import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RepairReportDetailScreen } from './RepairReportDetailScreen'
import {
  useDeleteRepairReport,
  useRepairReport,
  useRepairReportActions,
  useRepairReportPreview,
  useStartSingleReportAnalysis,
} from '@/lib/hooks/use-repair-reports'
import type {
  RepairReport,
  RepairReportDetail,
  RepairReportPreview,
} from '@/lib/api/repair-reports'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/lib/hooks/use-repair-reports', () => ({
  useRepairReports: vi.fn(),
  useRepairReport: vi.fn(),
  useRepairReportPreview: vi.fn(),
  useRepairReportActions: vi.fn(),
  useRepairAnalysisRuns: vi.fn(),
  useUploadRepairReport: vi.fn(),
  useStartRepairAnalysis: vi.fn(),
  useStartSingleReportAnalysis: vi.fn(),
  useDeleteRepairReport: vi.fn(),
}))

vi.mock('@/lib/hooks/use-llm-knowledge', () => ({
  useLLMBuilds: vi.fn(),
  useLLMBuild: vi.fn(),
  useLLMGuide: vi.fn(),
  useStartLLMBuild: vi.fn(),
}))

import {
  useLLMBuilds,
  useStartLLMBuild,
} from '@/lib/hooks/use-llm-knowledge'
import type { LLMKnowledgeBuild } from '@/lib/api/llm-knowledge'

const mockUseLLMBuilds = vi.mocked(useLLMBuilds)
const mockUseStartLLMBuild = vi.mocked(useStartLLMBuild)

const mockUseReport = vi.mocked(useRepairReport)
const mockUsePreview = vi.mocked(useRepairReportPreview)
const mockUseActions = vi.mocked(useRepairReportActions)
const mockUseAnalyze = vi.mocked(useStartSingleReportAnalysis)
const mockUseDeleteReport = vi.mocked(useDeleteRepairReport)

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })
  const spy = vi.spyOn(client, 'invalidateQueries')
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
  return { Wrapper, spy }
}

function renderDetail(reportId: string) {
  const { Wrapper, spy } = makeWrapper()
  const view = render(<RepairReportDetailScreen reportId={reportId} />, {
    wrapper: Wrapper,
  })
  return { ...view, spy }
}

const detailFor = (state: RepairReport['analysis_state']): RepairReportDetail => ({
  report: {
    id: 'repair_report:abc',
    filename: 'cmms.xlsx',
    size_bytes: 1024,
    sheet: 'Sheet1',
    column_count: 3,
    data_rows: 12,
    analysis_state: state,
    last_run_id: state === 'not_analyzed' ? null : 'repair_analysis_run:r1',
    last_error: state === 'failed' ? 'boom' : null,
    created: '2026-09-26T00:00:00',
    updated: '2026-09-26T00:00:00',
  },
  last_run:
    state === 'not_analyzed'
      ? null
      : {
          id: 'repair_analysis_run:r1',
          report_ids: ['repair_report:abc'],
          manifest: [],
          status: state === 'completed' ? 'completed' : state === 'failed' ? 'failed' : 'processing',
          command_id: 'command:1',
          error: null,
          record_count: null,
          equipment_count: null,
          failure_mode_count: null,
          guide_count: null,
          created: '2026-09-26T00:00:00',
          started_at: null,
          finished_at: null,
        },
})

const preview: RepairReportPreview = {
  sheet: 'Sheet1',
  columns: ['کد فرایندی', 'شرح درخواست', 'شرح تعمیر'],
  rows: [
    ['B104', 'عیب', 'تعمیر شد'],
    ['B104', null, 'قطعه تعویض شد'],
  ],
  total_data_rows: 12,
  truncated: true,
}

function mockHooks(state: RepairReport['analysis_state']) {  mockUseReport.mockReturnValue({
    data: detailFor(state),
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useRepairReport>)
  mockUsePreview.mockReturnValue({
    data: preview,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useRepairReportPreview>)
  mockUseActions.mockReturnValue({
    data: {
      report_id: 'repair_report:abc',
      analysis_key: 'a3f9c2e1',
      run_id: null,
      record_ids: [],
      repair_actions: [],
      verifications: [],
      post_repair_events: [],
      history_only_record_ids: [],
      warnings: [],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useRepairReportActions>)
  mockUseAnalyze.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useStartSingleReportAnalysis>)
  mockUseDeleteReport.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useDeleteRepairReport>)
  mockUseLLMBuilds.mockReturnValue({
    data: [],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useLLMBuilds>)
  mockUseStartLLMBuild.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useStartLLMBuild>)
}

describe('RepairReportDetailScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  /** This Radix Tabs version activates on mousedown, not click. */
  function selectTab(name: string) {
    const trigger = screen.getByRole('tab', { name })
    fireEvent.mouseDown(trigger, { button: 0 })
    fireEvent.click(trigger)
  }

  it('renders exactly the content and analysis tabs', () => {
    mockHooks('not_analyzed')
    renderDetail('repair_report:abc')
    expect(screen.getByText('repairReports.contentTab')).toBeInTheDocument()
    expect(screen.getByText('repairReports.analysisTab')).toBeInTheDocument()
    expect(screen.queryByText('repairReports.detailsTab')).not.toBeInTheDocument()
  })

  it('shows the 10-row preview with headers and Persian text', () => {
    mockHooks('not_analyzed')
    renderDetail('repair_report:abc')
    expect(screen.getByText('کد فرایندی')).toBeInTheDocument()
    expect(screen.getByText('عیب')).toBeInTheDocument()
    expect(screen.getByText('repairReports.previewNote')).toBeInTheDocument()
  })

  it('enables analysis only for not-analyzed reports', () => {
    mockHooks('not_analyzed')
    renderDetail('repair_report:abc')
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('repairReports.analyzeButton')).toBeEnabled()
  })

  it('disables analysis while processing', () => {
    mockHooks('processing')
    renderDetail('repair_report:abc')
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('repairReports.analyzeButton')).toBeDisabled()
    expect(screen.getByText('repairReports.statusProcessingDesc')).toBeInTheDocument()
  })

  it('disables analysis after completion', () => {
    mockHooks('completed')
    renderDetail('repair_report:abc')
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('repairReports.analyzeButton')).toBeDisabled()
    expect(screen.getByText('repairReports.viewGuideHint')).toBeInTheDocument()
  })

  it('surfaces the failure state with the backend error', () => {
    mockHooks('failed')
    renderDetail('repair_report:abc')
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('boom')).toBeInTheDocument()
  })

  it('refreshes guide caches when polling observes completion', () => {
    mockHooks('processing')
    const { rerender, spy } = renderDetail('repair_report:abc')
    spy.mockClear()
    mockHooks('completed')
    rerender(<RepairReportDetailScreen reportId="repair_report:abc" />)
    expect(spy).toHaveBeenCalledWith({ queryKey: ['troubleshooting'] })
    expect(spy).toHaveBeenCalledWith({
      queryKey: ['repair-reports'],
    })
    expect(spy).toHaveBeenCalledWith({
      queryKey: ['repair-reports', 'repair_report:abc', 'actions'],
    })
  })

  it('does not refresh guide caches while still processing', () => {
    mockHooks('processing')
    const { spy } = renderDetail('repair_report:abc')
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['troubleshooting'] })
  })

  it('starts an LLM build for this report and lists covering builds', () => {
    const mutate = vi.fn()
    mockHooks('completed')
    const covering: LLMKnowledgeBuild = {
      id: 'llm_knowledge_build:7',
      source_report_ids: ['repair_report:abc'],
      manifest: [],
      status: 'completed',
      command_id: 'command:9',
      model: 'model:chat',
      prompt_version: 'm12-v1',
      error: null,
      warnings: [],
      record_count: 4,
      failed_record_count: 0,
      created: '2026-09-28T10:00:00',
      started_at: null,
      finished_at: '2026-09-28T10:01:00',
    }
    const other: LLMKnowledgeBuild = {
      ...covering,
      id: 'llm_knowledge_build:8',
      source_report_ids: ['repair_report:other'],
    }
    mockUseLLMBuilds.mockReturnValue({
      data: [covering, other],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useLLMBuilds>)
    mockUseStartLLMBuild.mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useStartLLMBuild>)
    renderDetail('repair_report:abc')
    selectTab('repairReports.analysisTab')

    expect(screen.getByText('llmKnowledge.buildsTitle')).toBeInTheDocument()
    fireEvent.click(screen.getByText('llmKnowledge.startBuildButton'))
    expect(mutate).toHaveBeenCalledWith(['repair_report:abc'])
    // Only builds covering this report are listed (stable IDs, not names).
    const section = screen.getByTestId('llm-builds')
    expect(section.textContent).toContain('llm_knowledge_build:7'.slice(-6))
    expect(section.textContent).not.toContain('llm_knowledge_build:8'.slice(-6))
  })

  it('shows the LLM empty state when no build covers the report', () => {
    mockHooks('not_analyzed')
    renderDetail('repair_report:abc')
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('llmKnowledge.noBuildsDescription')).toBeInTheDocument()
    expect(screen.getByText('llmKnowledge.startBuildButton')).toBeEnabled()
  })

  it('disables the LLM build button while a build is active', () => {
    mockHooks('not_analyzed')
    mockUseLLMBuilds.mockReturnValue({
      data: [
        {
          id: 'llm_knowledge_build:7',
          source_report_ids: ['repair_report:abc'],
          manifest: [],
          status: 'running',
          command_id: 'command:9',
          model: null,
          prompt_version: 'm12-v1',
          error: null,
          warnings: [],
          record_count: null,
          failed_record_count: null,
          created: '2026-09-28T10:00:00',
          started_at: null,
          finished_at: null,
        },
      ],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useLLMBuilds>)
    renderDetail('repair_report:abc')
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('llmKnowledge.startBuildButton')).toBeDisabled()
  })
})
