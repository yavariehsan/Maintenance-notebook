import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SearchScreen } from './SearchScreen'
import { useSearch } from '@/lib/hooks/use-search'

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }))
const paramsHolder = vi.hoisted(() => ({
  current: new URLSearchParams(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: pushMock }),
  usePathname: () => '/search',
  useSearchParams: () => paramsHolder.current,
}))

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/search/NotebookScopeSelector', () => ({
  NotebookScopeSelector: () => null,
}))

vi.mock('@/components/search/StreamingResponse', () => ({
  StreamingResponse: () => null,
}))

vi.mock('@/components/search/AdvancedModelsDialog', () => ({
  AdvancedModelsDialog: () => null,
}))

vi.mock('@/components/search/SaveToNotebooksDialog', () => ({
  SaveToNotebooksDialog: () => null,
}))

vi.mock('@/lib/hooks/use-search', () => ({
  useSearch: vi.fn(),
}))

const askState = vi.hoisted(() => ({
  current: {
    sendAsk: vi.fn(),
    isStreaming: false,
    strategy: null,
    answers: [],
    finalAnswer: null,
    error: null,
    reset: vi.fn(),
  },
}))
vi.mock('@/lib/hooks/use-ask', () => ({
  useAsk: () => askState.current,
}))

vi.mock('@/lib/hooks/use-models', () => ({
  useModelDefaults: () => ({
    data: { default_chat_model: 'chat-m', default_embedding_model: 'emb-m' },
    isLoading: false,
  }),
  useModels: () => ({ data: [], isLoading: false }),
}))

const { openModalMock } = vi.hoisted(() => ({ openModalMock: vi.fn() }))
vi.mock('@/lib/hooks/use-modal-manager', () => ({
  useModalManager: () => ({ openModal: openModalMock }),
}))

const mockUseSearch = vi.mocked(useSearch)

function mutationStub(overrides = {}) {
  return {
    mutate: vi.fn(),
    data: undefined,
    isPending: false,
    isError: false,
    error: null,
    reset: vi.fn(),
    ...overrides,
  } as never
}

const result = {
  id: 'source:xyz',
  title: 'Pump manual',
  parent_id: 'source:xyz',
  final_score: 0.9,
  matches: ['pump pressure excerpt'],
  created: '2026-09-20T00:00:00Z',
  updated: '2026-09-20T00:00:00Z',
}

describe('SearchScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    paramsHolder.current = new URLSearchParams()
    askState.current = {
      sendAsk: vi.fn(),
      isStreaming: false,
      strategy: null,
      answers: [],
      finalAnswer: null,
      error: null,
      reset: vi.fn(),
    }
    mockUseSearch.mockReturnValue(mutationStub())
  })

  it('shows the initial ask state without auto-triggering', () => {
    const mutate = vi.fn()
    mockUseSearch.mockReturnValue(mutationStub({ mutate }))
    render(<SearchScreen />)

    expect(screen.getByText('searchPage.askYourKb')).toBeDefined()
    expect(mutate).not.toHaveBeenCalled()
  })

  it('auto-triggers search from URL params preserving query semantics', () => {
    paramsHolder.current = new URLSearchParams('q=pump&mode=search')
    const mutate = vi.fn()
    mockUseSearch.mockReturnValue(mutationStub({ mutate }))
    render(<SearchScreen />)

    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ query: 'pump', type: 'text' })
    )
  })

  it('renders results with hierarchy and score', () => {
    paramsHolder.current = new URLSearchParams('mode=search')
    mockUseSearch.mockReturnValue(
      mutationStub({
        data: { results: [result], total_count: 1, search_type: 'text' },
      })
    )
    render(<SearchScreen />)

    expect(screen.getByText('Pump manual')).toBeDefined()
    expect(screen.getByText('0.90')).toBeDefined()
  })

  it('renders an empty state when nothing matches', () => {
    paramsHolder.current = new URLSearchParams('mode=search')
    mockUseSearch.mockReturnValue(
      mutationStub({
        data: { results: [], total_count: 0, search_type: 'text' },
      })
    )
    render(<SearchScreen />)

    expect(screen.getByText('searchPage.noResultsFor')).toBeDefined()
  })

  it('shows an error panel with retry', () => {
    paramsHolder.current = new URLSearchParams('mode=search')
    const mutate = vi.fn()
    mockUseSearch.mockReturnValue(mutationStub({ mutate, isError: true }))
    render(<SearchScreen />)

    expect(screen.getByText('apiErrors.searchFailed')).toBeDefined()

    fireEvent.change(screen.getByLabelText('common.accessibility.enterSearch'), {
      target: { value: 'pump' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'common.refresh' }))
    expect(mutate).toHaveBeenCalledWith(
      expect.objectContaining({ query: 'pump' })
    )
  })

  it('opens result inspection from a result title', () => {
    paramsHolder.current = new URLSearchParams('mode=search')
    mockUseSearch.mockReturnValue(
      mutationStub({
        data: { results: [result], total_count: 1, search_type: 'text' },
      })
    )
    render(<SearchScreen />)

    fireEvent.click(screen.getByRole('button', { name: 'Pump manual' }))
    expect(openModalMock).toHaveBeenCalledWith('source', 'xyz')
  })

  it('reflects ask streaming state', () => {
    askState.current = { ...askState.current, isStreaming: true }
    render(<SearchScreen />)

    expect(screen.getByText('searchPage.processing')).toBeDefined()
  })
})
