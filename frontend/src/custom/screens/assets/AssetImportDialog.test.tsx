import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AssetImportDialog } from './AssetImportDialog'
import { useImportEquipment } from '@/lib/hooks/use-maintenance'
import type { EquipmentImportPreview } from '@/lib/types/api'

vi.mock('@/lib/hooks/use-maintenance', () => ({
  useImportEquipment: vi.fn(),
  useMaintenanceSources: vi.fn(),
  useMaintenanceAsk: vi.fn(),
}))

const mockUseImport = vi.mocked(useImportEquipment)

const previewFixture: EquipmentImportPreview = {
  total_rows: 3,
  valid_rows: [
    { row_number: 2, code: 'BR1', name: 'Horizontal Lathe Machine' },
    { row_number: 3, code: 'T53', name: 'Horizontal Lathe Machine' },
  ],
  issues: [{ row_number: 4, code: 'BR1', message: 'Duplicate code' }],
  imported_count: 0,
}

function renderDialog() {
  return render(<AssetImportDialog open onOpenChange={vi.fn()} />)
}

function selectFile() {
  const input = screen.getByLabelText('assets.importFile') as HTMLInputElement
  const file = new File(['dummy'], 'equipment.xlsx', {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  fireEvent.change(input, { target: { files: [file] } })
}

describe('AssetImportDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseImport.mockReturnValue({ mutateAsync: vi.fn(), isPending: false } as never)
  })

  it('renders the import title and file picker', () => {
    renderDialog()

    expect(screen.getByText('assets.importTitle')).toBeDefined()
    expect(screen.getByLabelText('assets.importFile')).toBeDefined()
  })

  it('runs a dry-run preview on file select and shows rows and issues', async () => {
    const mutateAsync = vi.fn().mockResolvedValue(previewFixture)
    mockUseImport.mockReturnValue({ mutateAsync, isPending: false } as never)
    renderDialog()

    selectFile()

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledWith(
        expect.objectContaining({ dryRun: true })
      )
    })
    // Both valid rows share the lathe description; BR1 doubles as the duplicate.
    expect(screen.getAllByText('Horizontal Lathe Machine').length).toBe(2)
    // BR1 appears once as a valid row and once as an in-file duplicate issue
    expect(screen.getAllByText('BR1').length).toBe(2)
    expect(screen.getByText('Duplicate code')).toBeDefined()
    // Confirm is enabled while valid rows exist
    expect(
      screen.getByRole('button', { name: 'assets.importConfirm' })
    ).toBeEnabled()
  })

  it('confirms the import with a persist call', async () => {
    const mutateAsync = vi
      .fn()
      .mockResolvedValueOnce(previewFixture)
      .mockResolvedValueOnce({ ...previewFixture, imported_count: 2 })
    mockUseImport.mockReturnValue({ mutateAsync, isPending: false } as never)
    renderDialog()

    selectFile()
    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: 'assets.importConfirm' })
      ).toBeEnabled()
    })
    fireEvent.click(screen.getByRole('button', { name: 'assets.importConfirm' }))

    await waitFor(() => {
      expect(mutateAsync).toHaveBeenLastCalledWith(
        expect.objectContaining({ dryRun: false })
      )
    })
  })

  it('disables confirm when no valid rows exist', async () => {
    const mutateAsync = vi.fn().mockResolvedValue({
      total_rows: 1,
      valid_rows: [],
      issues: [{ row_number: 2, code: null, message: 'Missing equipment Code.' }],
      imported_count: 0,
    })
    mockUseImport.mockReturnValue({ mutateAsync, isPending: false } as never)
    renderDialog()

    selectFile()

    await waitFor(() => {
      expect(screen.getByText('Missing equipment Code.')).toBeDefined()
    })
    expect(
      screen.getByRole('button', { name: 'assets.importConfirm' })
    ).toBeDisabled()
  })
})
