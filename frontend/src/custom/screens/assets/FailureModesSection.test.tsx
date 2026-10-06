import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { FailureModesSection } from './FailureModesSection'
import {
  useCreateFailureMode,
  useDeleteFailureMode,
  useFailureModes,
  useImportFailureModes,
  useUpdateFailureMode,
} from '@/lib/hooks/use-failure-modes'
import type { FailureModeResponse } from '@/lib/types/api'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/lib/hooks/use-failure-modes', () => ({
  useFailureModes: vi.fn(),
  useCreateFailureMode: vi.fn(),
  useUpdateFailureMode: vi.fn(),
  useDeleteFailureMode: vi.fn(),
  useImportFailureModes: vi.fn(),
}))

const mockUseFailureModes = vi.mocked(useFailureModes)

const mode = (overrides: Partial<FailureModeResponse> = {}): FailureModeResponse => ({
  id: 'failure_mode:abc',
  code: 'B138',
  label: 'تعویض ابزار',
  description: '',
  status: 'active',
  created: '2026-09-26T00:00:00',
  updated: '2026-09-26T00:00:00',
  ...overrides,
})

function mockList(data: FailureModeResponse[] | undefined) {
  mockUseFailureModes.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useFailureModes>)
  vi.mocked(useCreateFailureMode).mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useCreateFailureMode>)
  vi.mocked(useUpdateFailureMode).mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useUpdateFailureMode>)
  vi.mocked(useDeleteFailureMode).mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useDeleteFailureMode>)
  vi.mocked(useImportFailureModes).mockReturnValue({
    mutateAsync: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useImportFailureModes>)
}

describe('FailureModesSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the failure-mode database title and actions', () => {
    mockList([])
    render(<FailureModesSection />)
    expect(screen.getByText('failureModes.title')).toBeInTheDocument()
    expect(screen.getByText('failureModes.importButton')).toBeInTheDocument()
    expect(screen.getByText('failureModes.newMode')).toBeInTheDocument()
  })

  it('lists failure-mode records with equipment code and label', () => {
    mockList([mode()])
    render(<FailureModesSection />)
    expect(screen.getByText('B138')).toBeInTheDocument()
    expect(screen.getByText('تعویض ابزار')).toBeInTheDocument()
  })

  it('opens the manual creation dialog', () => {
    mockList([])
    render(<FailureModesSection />)
    fireEvent.click(screen.getByText('failureModes.newMode'))
    expect(screen.getByText('failureModes.newModeTitle')).toBeInTheDocument()
  })
})
