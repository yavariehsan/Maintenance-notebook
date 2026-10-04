import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RecentlyViewed } from './RecentlyViewed'
import { notebooksApi } from '@/lib/api/notebooks'
import type { RecentlyViewedResponse } from '@/lib/types/api'

vi.mock('@/lib/api/notebooks', () => ({
  notebooksApi: { recentlyViewed: vi.fn() },
}))

const mockRecentlyViewed = vi.mocked(notebooksApi.recentlyViewed)

const items: RecentlyViewedResponse[] = [
  {
    type: 'source',
    id: 'source:xyz',
    title: 'Pump manual',
    last_viewed_at: '2026-09-20T00:00:00Z',
  },
  {
    type: 'notebook',
    id: 'notebook:abc',
    title: 'Maintenance KB',
    last_viewed_at: '2026-09-21T00:00:00Z',
  },
]

function renderRecentlyViewed() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <RecentlyViewed />
    </QueryClientProvider>
  )
}

describe('RecentlyViewed', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('links a source entry to the source detail route', async () => {
    mockRecentlyViewed.mockResolvedValue(items)
    const { container } = renderRecentlyViewed()

    expect(await screen.findByText('Pump manual')).toBeDefined()
    const hrefs = [...container.querySelectorAll('a')].map((a) =>
      a.getAttribute('href')
    )
    // Intended contract: /sources/<raw id with colon> matches
    // app/(dashboard)/sources/[id]; the backend accepts raw and
    // percent-encoded forms (verified live: both HTTP 200).
    expect(hrefs).toContain('/sources/source:xyz')
  })

  it('links a notebook entry to the notebook detail route', async () => {
    mockRecentlyViewed.mockResolvedValue(items)
    const { container } = renderRecentlyViewed()

    expect(await screen.findByText('Maintenance KB')).toBeDefined()
    const hrefs = [...container.querySelectorAll('a')].map((a) =>
      a.getAttribute('href')
    )
    expect(hrefs).toContain('/notebooks/notebook%3Aabc')
  })
})
