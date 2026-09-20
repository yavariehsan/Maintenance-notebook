import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AssetRegistryScreen } from './AssetRegistryScreen'
import { useAssets, useCreateAsset, useUpdateAsset, useDeleteAsset } from '@/lib/hooks/use-assets'
import type { AssetResponse } from '@/lib/types/api'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
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
  }) =>
    open ? (
      <button data-testid="confirm-delete" onClick={onConfirm}>
        {title}
      </button>
    ) : null,
}))

vi.mock('@/lib/hooks/use-assets', () => ({
  useAssets: vi.fn(),
  useCreateAsset: vi.fn(),
  useUpdateAsset: vi.fn(),
  useDeleteAsset: vi.fn(),
}))

const mockUseAssets = vi.mocked(useAssets)
const mockUseCreate = vi.mocked(useCreateAsset)
const mockUseUpdate = vi.mocked(useUpdateAsset)
const mockUseDelete = vi.mocked(useDeleteAsset)

const asset: AssetResponse = {
  id: 'asset:abc',
  name: 'Pump P-101',
  description: 'Feed pump',
  asset_type: 'pump',
  status: 'active',
  location: 'Hall A',
  manufacturer: 'Acme',
  model: 'P-100',
  serial_number: 'SN-1',
  created: '2026-09-20T00:00:00Z',
  updated: '2026-09-20T00:00:00Z',
}

function mockQueries(overrides = {}) {
  mockUseAssets.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  } as never)
  mockUseCreate.mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as never)
  mockUseUpdate.mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as never)
  mockUseDelete.mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as never)
}

describe('AssetRegistryScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockQueries()
  })

  it('shows a loading state', () => {
    mockQueries({ isLoading: true })
    const { container } = render(<AssetRegistryScreen />)

    expect(container.querySelector('.animate-spin')).not.toBeNull()
  })

  it('shows an error state with retry', () => {
    const refetch = vi.fn()
    mockQueries({ isError: true, refetch })
    render(<AssetRegistryScreen />)

    expect(screen.getByText('assets.loadFailed')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'common.refresh' }))
    expect(refetch).toHaveBeenCalled()
  })

  it('shows an empty state with a create action', () => {
    mockQueries({ data: [] })
    render(<AssetRegistryScreen />)

    expect(screen.getByText('assets.emptyTitle')).toBeDefined()
    expect(screen.getByRole('button', { name: 'assets.newAsset' })).toBeDefined()
  })

  it('renders populated assets with metadata', () => {
    mockQueries({ data: [asset] })
    render(<AssetRegistryScreen />)

    expect(screen.getByText('Pump P-101')).toBeDefined()
    expect(screen.getByText('Hall A')).toBeDefined()
    expect(screen.getByText('active')).toBeDefined()
  })

  it('creates an asset through the dialog', async () => {
    const mutateAsync = vi.fn()
    mockQueries({ data: [] })
    mockUseCreate.mockReturnValue({ mutateAsync, isPending: false } as never)
    render(<AssetRegistryScreen />)

    fireEvent.click(screen.getByRole('button', { name: 'assets.newAsset' }))
    fireEvent.change(screen.getByLabelText('common.name'), { target: { value: 'Pump P-102' } })
    const saveButton = screen.getByRole('button', { name: 'common.save' })
    await waitFor(() => {
      expect(saveButton).toBeEnabled()
    })
    fireEvent.click(saveButton)

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ name: 'Pump P-102' })
      )
    })
  })

  it('deletes an asset through the confirm flow', async () => {
    const mutateAsync = vi.fn()
    mockQueries({ data: [asset] })
    mockUseDelete.mockReturnValue({ mutateAsync, isPending: false } as never)
    const { container } = render(<AssetRegistryScreen />)

    const rowDelete = container.querySelector('tbody tr button.text-destructive')
    expect(rowDelete).not.toBeNull()
    fireEvent.click(rowDelete!)
    fireEvent.click(screen.getByTestId('confirm-delete'))

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith('asset:abc')
    })
  })
})
