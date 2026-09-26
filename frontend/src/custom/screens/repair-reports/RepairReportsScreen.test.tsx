import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { RepairReportsScreen } from './RepairReportsScreen'
import { useRepairReports, useUploadRepairReport } from '@/lib/hooks/use-repair-reports'
import type { RepairReport } from '@/lib/api/repair-reports'

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

const mockUseRepairReports = vi.mocked(useRepairReports)
const mockUseUpload = vi.mocked(useUploadRepairReport)

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

  it('shows the error state with retry', () => {
    mockList(undefined, { isError: true })
    render(<RepairReportsScreen />)
    expect(screen.getByText('repairReports.loadFailed')).toBeInTheDocument()
  })
})
