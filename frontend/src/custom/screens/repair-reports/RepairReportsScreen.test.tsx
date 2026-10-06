import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { RepairReportsScreen } from './RepairReportsScreen'
import {
  useDeleteRepairReport,
  useRepairReports,
  useUploadRepairReport,
} from '@/lib/hooks/use-repair-reports'
import type { RepairReport } from '@/lib/api/repair-reports'

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

const mockUseRepairReports = vi.mocked(useRepairReports)
const mockUseUpload = vi.mocked(useUploadRepairReport)
const mockUseDelete = vi.mocked(useDeleteRepairReport)

const report = (overrides: Partial<RepairReport> = {}): RepairReport => ({
  id: 'repair_report:abc',
  filename: 'cmms.xlsx',
  size_bytes: 1024,
  sheet: 'Sheet1',
  column_count: 9,
  data_rows: 120,
  analysis_state: 'not_analyzed',
  last_run_id: null,
  last_error: null,
  created: '2026-09-26T00:00:00',
  updated: '2026-09-26T00:00:00',
  ...overrides,
})

function mockList(data: RepairReport[] | undefined, states = {}) {
  mockUseRepairReports.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...states,
  } as unknown as ReturnType<typeof useRepairReports>)
  mockUseUpload.mockReturnValue({
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useUploadRepairReport>)
  mockUseDelete.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useDeleteRepairReport>)
}

describe('RepairReportsScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the collection title and upload action', () => {
    mockList([])
    render(<RepairReportsScreen />)
    expect(screen.getByText('repairReports.title')).toBeInTheDocument()
    expect(screen.getAllByText('repairReports.uploadButton').length).toBeGreaterThan(0)
  })

  it('shows the empty state when no reports exist', () => {
    mockList([])
    render(<RepairReportsScreen />)
    expect(screen.getByText('repairReports.emptyTitle')).toBeInTheDocument()
  })

  it('lists reports with distinct analysis states', () => {
    mockList([
      report({ id: 'repair_report:a', analysis_state: 'not_analyzed' }),
      report({ id: 'repair_report:b', filename: 'b.xlsx', analysis_state: 'processing' }),
      report({ id: 'repair_report:c', filename: 'c.xlsx', analysis_state: 'completed' }),
      report({ id: 'repair_report:d', filename: 'd.xlsx', analysis_state: 'failed' }),
    ])
    render(<RepairReportsScreen />)
    expect(screen.getByText('cmms.xlsx')).toBeInTheDocument()
    expect(screen.getByText('b.xlsx')).toBeInTheDocument()
    expect(screen.getByText('repairReports.statusNotAnalyzed')).toBeInTheDocument()
    expect(screen.getByText('repairReports.statusProcessing')).toBeInTheDocument()
    expect(screen.getByText('repairReports.statusCompleted')).toBeInTheDocument()
    expect(screen.getByText('repairReports.statusFailed')).toBeInTheDocument()
  })

  it('renders the cover-analysis column from the real LLM build state', () => {
    mockList([
      report({ id: 'repair_report:a', llm_status: 'not_started' }),
      report({ id: 'repair_report:b', filename: 'b.xlsx', llm_status: 'running' }),
      report({ id: 'repair_report:c', filename: 'c.xlsx', llm_status: 'completed' }),
    ])
    const { container } = render(<RepairReportsScreen />)
    // Dedicated header with the exact required label key.
    expect(screen.getByText('repairReports.llmStatusColumn')).toBeInTheDocument()
    // Values come from the backend LLM state, mapped through llmKnowledge keys.
    expect(screen.getByText('llmKnowledge.statusNotStarted')).toBeInTheDocument()
    expect(screen.getByText('llmKnowledge.statusRunning')).toBeInTheDocument()
    expect(screen.getByText('llmKnowledge.statusCompleted')).toBeInTheDocument()
    // Same table typography as the existing analysis-status cells.
    const badges = container.querySelectorAll('td.h-12.px-4 > .font-mono.text-\\[11px\\]')
    expect(badges.length).toBeGreaterThanOrEqual(6)
  })

  it('shows the error state with retry', () => {
    mockList(undefined, { isError: true })
    render(<RepairReportsScreen />)
    expect(screen.getByText('repairReports.loadFailed')).toBeInTheDocument()
  })

  it('offers delete for idle reports but not for active ones', () => {
    mockList([
      report({ id: 'repair_report:a', analysis_state: 'not_analyzed' }),
      report({ id: 'repair_report:b', filename: 'b.xlsx', analysis_state: 'processing' }),
    ])
    render(<RepairReportsScreen />)
    // One delete button (idle report); the processing row shows an em dash.
    expect(screen.getAllByRole('button', { name: 'repairReports.deleteReport' })).toHaveLength(1)
  })

  it('deletes a report through the confirm flow by stable ID', () => {
    mockList([report({ id: 'repair_report:abc' })])
    const mutate = vi.fn()
    mockUseDelete.mockReturnValue({
      mutate,
      isPending: false,
    } as unknown as ReturnType<typeof useDeleteRepairReport>)
    render(<RepairReportsScreen />)

    fireEvent.click(screen.getByRole('button', { name: 'repairReports.deleteReport' }))
    expect(screen.getByText('repairReports.deleteReportTitle')).toBeInTheDocument()
    const confirmButtons = screen.getAllByRole('button', { name: 'repairReports.deleteReport' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])
    expect(mutate).toHaveBeenCalledWith('repair_report:abc', expect.anything())
  })
})
