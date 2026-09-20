import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NotebookListScreen } from './NotebookListScreen'
import { useNotebooks } from '@/lib/hooks/use-notebooks'
import type { NotebookResponse } from '@/lib/types/api'
import { useNotebookViewStore } from '@/lib/stores/notebook-view-store'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/app/(dashboard)/notebooks/components/RecentlyViewed', () => ({
  RecentlyViewed: () => null,
}))

vi.mock('@/components/notebooks/CreateNotebookDialog', () => ({
  CreateNotebookDialog: () => null,
}))

vi.mock('@/lib/hooks/use-notebooks', () => ({
  useNotebooks: vi.fn(),
  useNotebookDeletePreview: () => ({ data: null, isLoading: false, error: null }),
  useUpdateNotebook: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteNotebook: () => ({ mutate: vi.fn(), isPending: false }),
}))

vi.mock('@/lib/stores/notebook-view-store', () => ({
  useNotebookViewStore: vi.fn(),
}))

const mockUseNotebooks = vi.mocked(useNotebooks)
const mockViewStore = vi.mocked(useNotebookViewStore)

function setViewMode(mode: 'tile' | 'list') {
  mockViewStore.mockImplementation(
    ((selector: (state: { viewMode: string; setViewMode: () => void }) => unknown) =>
      selector({ viewMode: mode, setViewMode: vi.fn() })) as never
  )
}

const notebook: NotebookResponse = {
  id: 'notebook:abc',
  name: 'Field maintenance',
  description: 'Turbine checklists',
  archived: false,
  created: '2026-09-20T00:00:00Z',
  updated: '2026-09-20T00:00:00Z',
  source_count: 2,
  note_count: 1,
}

function renderScreen() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <NotebookListScreen />
    </QueryClientProvider>
  )
}

describe('NotebookListScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setViewMode('tile')
  })

  it('shows a loading state while notebooks load', () => {
    mockUseNotebooks.mockReturnValue({ data: undefined, isLoading: true } as never)
    const { container } = renderScreen()

    expect(container.querySelector('.animate-spin')).not.toBeNull()
  })

  it('shows an error state with retry', () => {
    const refetch = vi.fn()
    mockUseNotebooks.mockReturnValue({ data: undefined, isLoading: false, isError: true, refetch } as never)
    renderScreen()

    expect(screen.getByText('common.error')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'common.refresh' }))
    expect(refetch).toHaveBeenCalled()
  })

  it('shows an empty state with a create action', () => {
    mockUseNotebooks.mockReturnValue({ data: [], isLoading: false } as never)
    renderScreen()

    expect(screen.getByText('common.noResults')).toBeDefined()
    // Toolbar plus the empty-state action both offer notebook creation
    expect(
      screen.getAllByRole('button', { name: 'notebooks.newNotebook' }).length
    ).toBeGreaterThanOrEqual(2)
  })

  it('renders populated notebooks that navigate to detail pages', () => {
    setViewMode('list')
    mockUseNotebooks.mockReturnValue({ data: [notebook], isLoading: false } as never)
    renderScreen()

    const link = screen.getByRole('link', { name: 'Field maintenance' })
    expect(link.getAttribute('href')).toBe('/notebooks/notebook%3Aabc')
  })

  it('filters notebooks by search term', () => {
    mockUseNotebooks.mockReturnValue({ data: [notebook], isLoading: false } as never)
    renderScreen()

    fireEvent.change(screen.getByLabelText('common.accessibility.searchNotebooks'), {
      target: { value: 'no-such-name' },
    })

    expect(screen.queryByText('Field maintenance')).toBeNull()
    // Active and archived sections both report no matches
    expect(screen.getAllByText('common.noMatches')).toHaveLength(2)
  })
})
