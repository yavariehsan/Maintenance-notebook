import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { RepairReportDetailScreen } from './RepairReportDetailScreen'
import {
  useRepairReport,
  useRepairReportPreview,
  useStartRepairAnalysis,
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
  useRepairAnalysisRuns: vi.fn(),
  useUploadRepairReport: vi.fn(),
  useStartRepairAnalysis: vi.fn(),
}))

const mockUseReport = vi.mocked(useRepairReport)
const mockUsePreview = vi.mocked(useRepairReportPreview)
const mockUseAnalyze = vi.mocked(useStartRepairAnalysis)

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
  mockUseAnalyze.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useStartRepairAnalysis>)
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
    render(<RepairReportDetailScreen reportId="repair_report:abc" />)
    expect(screen.getByText('repairReports.contentTab')).toBeInTheDocument()
    expect(screen.getByText('repairReports.analysisTab')).toBeInTheDocument()
    expect(screen.queryByText('repairReports.detailsTab')).not.toBeInTheDocument()
  })

  it('shows the 10-row preview with headers and Persian text', () => {
    mockHooks('not_analyzed')
    render(<RepairReportDetailScreen reportId="repair_report:abc" />)
    expect(screen.getByText('کد فرایندی')).toBeInTheDocument()
    expect(screen.getByText('عیب')).toBeInTheDocument()
    expect(screen.getByText('repairReports.previewNote')).toBeInTheDocument()
  })

  it('enables analysis only for not-analyzed reports', () => {
    mockHooks('not_analyzed')
    render(<RepairReportDetailScreen reportId="repair_report:abc" />)
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('repairReports.analyzeButton')).toBeEnabled()
  })

  it('disables analysis while processing', () => {
    mockHooks('processing')
    render(<RepairReportDetailScreen reportId="repair_report:abc" />)
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('repairReports.analyzeButton')).toBeDisabled()
    expect(screen.getByText('repairReports.statusProcessingDesc')).toBeInTheDocument()
  })

  it('disables analysis after completion', () => {
    mockHooks('completed')
    render(<RepairReportDetailScreen reportId="repair_report:abc" />)
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('repairReports.analyzeButton')).toBeDisabled()
    expect(screen.getByText('repairReports.viewGuideHint')).toBeInTheDocument()
  })

  it('surfaces the failure state with the backend error', () => {
    mockHooks('failed')
    render(<RepairReportDetailScreen reportId="repair_report:abc" />)
    selectTab('repairReports.analysisTab')
    expect(screen.getByText('boom')).toBeInTheDocument()
  })
})
