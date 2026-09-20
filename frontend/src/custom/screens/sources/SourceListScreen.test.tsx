import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SourceListScreen } from './SourceListScreen'
import { sourcesApi } from '@/lib/api/sources'
import { toast } from 'sonner'
import type { SourceListResponse } from '@/lib/types/api'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/sources/AddSourceDialog', () => ({
  AddSourceDialog: () => null,
}))

vi.mock('@/components/common/ConfirmDialog', () => ({
  ConfirmDialog: ({
    open,
    title,
    onConfirm,
  }: {
    open: boolean
    title: string
    onConfirm: () => void
  }) => (open ? <button onClick={onConfirm}>{title}</button> : null),
}))

const push = vi.fn()
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
  usePathname: () => '/sources',
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/lib/api/sources', () => ({
  sourcesApi: { list: vi.fn(), delete: vi.fn() },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

const mockList = vi.mocked(sourcesApi.list)
const mockDelete = vi.mocked(sourcesApi.delete)
const mockPush = vi.mocked(push)

const source: SourceListResponse = {
  id: 'source:xyz',
  title: 'Pump manual',
  asset: { url: 'https://example.com/manual' },
  embedded: true,
  embedded_chunks: 3,
  insights_count: 2,
  created: '2026-09-20T00:00:00Z',
  updated: '2026-09-20T00:00:00Z',
}

describe('SourceListScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows a loading state while sources load', () => {
    mockList.mockReturnValue(new Promise(() => {}))
    const { container } = render(<SourceListScreen />)

    expect(container.querySelector('.animate-spin')).not.toBeNull()
  })

  it('shows an error state when loading fails', async () => {
    mockList.mockRejectedValue(new Error('down'))
    render(<SourceListScreen />)

    expect(await screen.findByText('sources.failedToLoad')).toBeDefined()
  })

  it('shows an empty state with a create action', async () => {
    mockList.mockResolvedValue([])
    render(<SourceListScreen />)

    expect(await screen.findByText('sources.noSourcesYet')).toBeDefined()
    expect(screen.getByRole('button', { name: 'sources.newSource' })).toBeDefined()
  })

  it('renders populated sources and sorts by title', async () => {
    mockList.mockResolvedValue([source])
    render(<SourceListScreen />)

    expect(await screen.findByText('Pump manual')).toBeDefined()
    expect(mockList).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'updated', sort_order: 'desc' })
    )

    fireEvent.click(screen.getByRole('button', { name: 'common.title' }))
    await waitFor(() => {
      expect(mockList).toHaveBeenCalledWith(
        expect.objectContaining({ sort_by: 'title', sort_order: 'desc' })
      )
    })
  })

  it('navigates to source detail on row click', async () => {
    mockList.mockResolvedValue([source])
    const { container } = render(<SourceListScreen />)

    await screen.findByText('Pump manual')
    const row = container.querySelector('tbody tr')
    expect(row).not.toBeNull()
    fireEvent.click(row!)

    expect(mockPush).toHaveBeenCalledWith('/sources/source:xyz')
  })

  it('deletes a source through the confirm flow', async () => {
    mockList.mockResolvedValue([source])
    mockDelete.mockResolvedValue(undefined as never)
    const { container } = render(<SourceListScreen />)

    await screen.findByText('Pump manual')
    const deleteButton = container.querySelector('tbody tr button')
    expect(deleteButton).not.toBeNull()
    fireEvent.click(deleteButton!)
    expect(await screen.findByText('sources.delete')).toBeDefined()

    fireEvent.click(screen.getByRole('button', { name: 'sources.delete' }))
    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith('source:xyz')
    })
    expect(toast.success).toHaveBeenCalled()
    expect(screen.queryByText('Pump manual')).toBeNull()
  })
})
