import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SmartMaintenanceGuideScreen } from './SmartMaintenanceGuideScreen'
import { useAssets } from '@/lib/hooks/use-assets'
import { useMaintenanceAsk, useMaintenanceSources } from '@/lib/hooks/use-maintenance'
import type { AssetResponse } from '@/lib/types/api'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/lib/hooks/use-assets', () => ({
  useAssets: vi.fn(),
  useAsset: vi.fn(),
  useCreateAsset: vi.fn(),
  useUpdateAsset: vi.fn(),
  useDeleteAsset: vi.fn(),
}))

vi.mock('@/lib/hooks/use-maintenance', () => ({
  useMaintenanceSources: vi.fn(),
  useMaintenanceAsk: vi.fn(),
  useImportEquipment: vi.fn(),
}))

const mockUseAssets = vi.mocked(useAssets)
const mockUseSources = vi.mocked(useMaintenanceSources)
const mockUseAsk = vi.mocked(useMaintenanceAsk)

const assets: AssetResponse[] = [
  {
    id: 'asset:br1',
    name: 'Horizontal Lathe Machine',
    description: '',
    asset_type: 'Horizontal Turning',
    status: 'active',
    location: 'Shop2',
    manufacturer: 'Machine Sazi Tabriz (MST)',
    model: 'TC 20-HS',
    serial_number: null,
    code: 'BR1',
    factory: 'Shop2',
    zone_description: 'Production',
    site_description: 'Machining',
    plant_description: 'Blade',
    main_class: 'Machine Tools',
    sub_class: 'CNC',
    created: '2026-09-20T00:00:00Z',
    updated: '2026-09-20T00:00:00Z',
  },
]

function mockHooks(overrides: {
  assetsData?: AssetResponse[] | undefined
  assetsLoading?: boolean
  assetsError?: boolean
  sourcesData?: { id: string; title: string | null }[]
} = {}) {
  mockUseAssets.mockReturnValue({
    data: overrides.assetsData,
    isLoading: overrides.assetsLoading ?? false,
    isError: overrides.assetsError ?? false,
    refetch: vi.fn(),
  } as never)
  mockUseSources.mockReturnValue({
    data: overrides.sourcesData ?? [],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as never)
  mockUseAsk.mockReturnValue({ mutateAsync: vi.fn(), isPending: false, isError: false } as never)
}

async function selectEquipment() {
  fireEvent.click(screen.getByRole('combobox'))
  const option = await screen.findByRole('option', { name: /BR1/ })
  fireEvent.click(option)
  await waitFor(() => {
    expect(screen.getByPlaceholderText('maintenance.questionPlaceholder')).toBeDefined()
  })
}

describe('SmartMaintenanceGuideScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Radix Select calls scrollIntoView, which jsdom does not implement.
    window.HTMLElement.prototype.scrollIntoView = vi.fn()
    mockHooks({ assetsData: assets })
  })

  it('renders the guide title and equipment selector', () => {
    render(<SmartMaintenanceGuideScreen />)

    expect(screen.getByText('maintenance.title')).toBeDefined()
    expect(screen.getByRole('combobox')).toBeDefined()
  })

  it('shows an empty state when no equipment exists', () => {
    mockHooks({ assetsData: [] })
    render(<SmartMaintenanceGuideScreen />)

    expect(screen.getByText('maintenance.noEquipmentTitle')).toBeDefined()
  })

  it('shows an error state with retry when equipment loading fails', () => {
    const refetch = vi.fn()
    mockUseAssets.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      refetch,
    } as never)
    render(<SmartMaintenanceGuideScreen />)

    expect(screen.getByText('maintenance.equipmentLoadFailed')).toBeDefined()
    fireEvent.click(screen.getByRole('button', { name: 'common.refresh' }))
    expect(refetch).toHaveBeenCalled()
  })

  it('asks a question and renders the grounded answer with sources', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      equipment_code: 'BR1',
      status: 'ok',
      answer: 'The spindle bearing failed twice.',
      sources: [{ id: 'source:abc', title: 'CMMS-Report BR1' }],
    })
    mockUseAsk.mockReturnValue({ mutateAsync, isPending: false, isError: false } as never)
    render(<SmartMaintenanceGuideScreen />)

    await selectEquipment()
    fireEvent.change(screen.getByPlaceholderText('maintenance.questionPlaceholder'), {
      target: { value: 'What failed?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'maintenance.askButton' }))

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith({
        equipment_code: 'BR1',
        question: 'What failed?',
      })
    })
    expect(await screen.findByText('The spindle bearing failed twice.')).toBeDefined()
    expect(screen.getByText('CMMS-Report BR1')).toBeDefined()
  })

  it('shows the no-sources state when the equipment has no CMMS reports', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      equipment_code: 'BR1',
      status: 'no_sources',
      answer: '',
      sources: [],
    })
    mockUseAsk.mockReturnValue({ mutateAsync, isPending: false, isError: false } as never)
    render(<SmartMaintenanceGuideScreen />)

    await selectEquipment()
    fireEvent.change(screen.getByPlaceholderText('maintenance.questionPlaceholder'), {
      target: { value: 'What failed?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'maintenance.askButton' }))

    expect(await screen.findByText('maintenance.noSourcesTitle')).toBeDefined()
  })

  it('shows the no-context state when reports hold nothing relevant', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      equipment_code: 'BR1',
      status: 'no_context',
      answer: '',
      sources: [{ id: 'source:abc', title: 'CMMS-Report BR1' }],
    })
    mockUseAsk.mockReturnValue({ mutateAsync, isPending: false, isError: false } as never)
    render(<SmartMaintenanceGuideScreen />)

    await selectEquipment()
    fireEvent.change(screen.getByPlaceholderText('maintenance.questionPlaceholder'), {
      target: { value: 'Unrelated?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'maintenance.askButton' }))

    expect(await screen.findByText('maintenance.noContextTitle')).toBeDefined()
  })
})
