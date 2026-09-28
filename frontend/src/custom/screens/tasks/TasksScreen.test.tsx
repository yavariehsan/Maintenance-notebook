import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TasksScreen } from './TasksScreen'
import {
  formatTaskChunks,
  formatTaskTime,
  getTaskStatusKind,
  getTaskStatusLabelKey,
} from './task-helpers'
import { useDeleteTask, useClearTasksHistory, useTasks } from '@/lib/hooks/use-tasks'
import type { TaskItem } from '@/lib/api/tasks'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/lib/hooks/use-tasks', () => ({
  useTasks: vi.fn(),
  useDeleteTask: vi.fn(),
  useClearTasksHistory: vi.fn(),
}))

const mockUseTasks = vi.mocked(useTasks)
const mockUseDeleteTask = vi.mocked(useDeleteTask)
const mockUseClearHistory = vi.mocked(useClearTasksHistory)

const runningTask: TaskItem = {
  job_id: 'command:run1',
  item_type: 'source',
  source_id: 'source:abc',
  source_title: 'CMMS Report',
  status: 'running',
  processed_chunks: 12,
  total_chunks: 351,
  percentage: 3.4,
  started_at: '2026-09-22T10:00:00Z',
  updated_at: '2026-09-22T10:01:00Z',
}

const queuedTask: TaskItem = {
  job_id: 'command:new1',
  item_type: 'source',
  source_id: 'source:def',
  source_title: null,
  status: 'new',
  processed_chunks: null,
  total_chunks: null,
  percentage: null,
}

const failedTask: TaskItem = {
  job_id: 'command:fail1',
  item_type: 'source',
  source_id: 'source:xyz',
  source_title: 'Old Report',
  status: 'failed',
  processed_chunks: 3,
  total_chunks: 40,
  percentage: 7.5,
  error_message: 'Failed to generate embeddings (batch 1/4)',
}

const completedTask: TaskItem = {
  job_id: 'command:done1',
  item_type: 'source',
  source_id: 'source:abc',
  source_title: 'CMMS Report',
  status: 'completed',
  processed_chunks: 351,
  total_chunks: 351,
  percentage: 100,
  chunks_created: 351,
}

const runningRepairTask: TaskItem = {
  job_id: 'command:analysis1',
  item_type: 'repair_analysis',
  command_name: 'analyze_repair_reports',
  run_id: 'repair_analysis_run:run1',
  title: 'Sample-1.xlsx',
  status: 'running',
  processed_chunks: null,
  total_chunks: null,
  percentage: null,
}

const failedRepairTask: TaskItem = {
  job_id: 'command:analysis2',
  item_type: 'repair_analysis',
  command_name: 'analyze_repair_reports',
  run_id: 'repair_analysis_run:run2',
  title: 'a.xlsx, b.xlsx',
  status: 'failed',
  processed_chunks: null,
  total_chunks: null,
  percentage: null,
  error_message: 'Stored file for report repair_report:zzz is missing.',
}

function mockQuery(overrides = {}) {
  mockUseTasks.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  } as never)
  mockUseDeleteTask.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as never)
  mockUseClearHistory.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as never)
}

describe('TasksScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockQuery()
  })

  it('shows a loading state', () => {
    mockQuery({ isLoading: true })
    const { container } = render(<TasksScreen />)

    expect(container.querySelector('.animate-spin')).not.toBeNull()
  })

  it('shows an error state with retry', () => {
    const refetch = vi.fn()
    mockQuery({ isError: true, refetch })
    render(<TasksScreen />)

    expect(screen.getByText('tasks.loadFailed')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'common.refresh' }))
    expect(refetch).toHaveBeenCalled()
  })

  it('shows an empty state when there are no jobs', () => {
    mockQuery({ data: [] })
    render(<TasksScreen />)

    expect(screen.getByText('tasks.emptyTitle')).toBeDefined()
    expect(screen.getByText('tasks.emptyDescription')).toBeDefined()
  })

  it('renders running jobs with real progress and chunk counts', () => {
    mockQuery({ data: [runningTask] })
    render(<TasksScreen />)

    expect(screen.getByText('CMMS Report')).toBeDefined()
    expect(screen.getByText('source:abc')).toBeDefined()
    expect(screen.getByText('tasks.processing')).toBeDefined()
    expect(screen.getByText('3.4%')).toBeDefined()
    expect(screen.getByText('12 / 351')).toBeDefined()
  })

  it('renders queued jobs with an honest indeterminate state, not a fake percentage', () => {
    mockQuery({ data: [queuedTask] })
    const { container } = render(<TasksScreen />)

    expect(screen.getByText('tasks.pending')).toBeDefined()
    expect(screen.getByText('tasks.inProgress')).toBeDefined()
    expect(container.querySelector('.animate-pulse')).not.toBeNull()
    expect(screen.queryByText(/%/)).toBeNull()
  })

  it('renders completed jobs at 100% and failed jobs with their error', () => {
    mockQuery({ data: [completedTask, failedTask] })
    render(<TasksScreen />)

    expect(screen.getByText('tasks.completed')).toBeDefined()
    expect(screen.getByText('100%')).toBeDefined()
    expect(screen.getByText('tasks.failed')).toBeDefined()
    expect(screen.getByText('Failed to generate embeddings (batch 1/4)')).toBeDefined()
  })

  it('shows the repair analysis run alongside embedding jobs', () => {
    mockQuery({ data: [runningTask, runningRepairTask] })
    const { container } = render(<TasksScreen />)

    // Same active state on both screens: filenames + run id, no fake %.
    // (The embedding job keeps its real 3.4%; the repair row adds none.)
    expect(screen.getByText('Sample-1.xlsx')).toBeDefined()
    expect(screen.getByText('repair_analysis_run:run1')).toBeDefined()
    expect(screen.getAllByText(/%/)).toHaveLength(1)
    expect(container.querySelector('.animate-pulse')).not.toBeNull()
  })

  it('shows failed repair analysis with its error and run reference', () => {
    mockQuery({ data: [failedRepairTask] })
    render(<TasksScreen />)

    expect(screen.getByText('a.xlsx, b.xlsx')).toBeDefined()
    expect(screen.getByText('repair_analysis_run:run2')).toBeDefined()
    expect(screen.getByText('tasks.failed')).toBeDefined()
    expect(
      screen.getByText('Stored file for report repair_report:zzz is missing.'),
    ).toBeDefined()
  })

  it('offers delete only for terminal jobs, never for active ones', () => {
    mockQuery({ data: [runningTask, completedTask] })
    render(<TasksScreen />)

    // One delete button (completed) ; the running row shows an em dash.
    expect(screen.getAllByRole('button', { name: 'tasks.deleteTask' })).toHaveLength(1)
  })

  it('deletes a terminal task through the confirm flow', () => {
    const mutate = vi.fn()
    mockUseTasks.mockReturnValue({
      data: [failedTask],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never)
    mockUseDeleteTask.mockReturnValue({ mutate, isPending: false } as never)
    render(<TasksScreen />)

    fireEvent.click(screen.getByRole('button', { name: 'tasks.deleteTask' }))
    expect(screen.getByText('tasks.deleteTaskTitle')).toBeDefined()
    const confirmButtons = screen.getAllByRole('button', { name: 'tasks.deleteTask' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])
    expect(mutate).toHaveBeenCalledWith('command:fail1', expect.anything())
  })

  it('clears terminal history through a confirm flow without touching active jobs', () => {
    const mutate = vi.fn()
    mockUseTasks.mockReturnValue({
      data: [runningTask, completedTask],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never)
    mockUseClearHistory.mockReturnValue({ mutate, isPending: false } as never)
    render(<TasksScreen />)

    // Clearly visible action; both rows stay visible until confirmed.
    fireEvent.click(screen.getByRole('button', { name: 'tasks.clearHistory' }))
    expect(screen.getByText('tasks.clearHistoryTitle')).toBeDefined()
    expect(screen.getByText('tasks.clearHistoryDescription')).toBeDefined()
    const confirmButtons = screen.getAllByRole('button', { name: 'tasks.clearHistory' })
    fireEvent.click(confirmButtons[confirmButtons.length - 1])
    expect(mutate).toHaveBeenCalledTimes(1)
  })

  it('renders API order so newest-updated tasks come first', () => {
    mockUseTasks.mockReturnValue({
      data: [failedTask, completedTask],
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as never)
    render(<TasksScreen />)
    const rows = document.querySelectorAll('tbody tr')
    // First body row belongs to the first task in API order (the failed
    // task spans two rows: main + error detail).
    expect(rows[0]?.textContent).toContain('Old Report')
    expect(rows[2]?.textContent).toContain('CMMS Report')
  })
})

describe('task-helpers', () => {
  it('maps backend statuses to localized label keys', () => {
    expect(getTaskStatusKind('new')).toBe('pending')
    expect(getTaskStatusKind('running')).toBe('processing')
    expect(getTaskStatusKind('completed')).toBe('completed')
    expect(getTaskStatusKind('failed')).toBe('failed')
    expect(getTaskStatusKind('canceled')).toBe('cancelled')
    expect(getTaskStatusLabelKey('running')).toBe('tasks.processing')
  })

  it('formats chunk counters honestly', () => {
    expect(formatTaskChunks({ processed_chunks: 12, total_chunks: 351 })).toBe('12 / 351')
    expect(formatTaskChunks({ processed_chunks: 12, total_chunks: null })).toBe('12')
    expect(formatTaskChunks({ processed_chunks: null, total_chunks: null })).toBe('—')
  })

  it('formats times defensively', () => {
    expect(formatTaskTime(null)).toBe('—')
    expect(formatTaskTime('not-a-date')).toBe('—')
    expect(formatTaskTime('2026-09-22T10:00:00Z')).not.toBe('—')
  })
})
