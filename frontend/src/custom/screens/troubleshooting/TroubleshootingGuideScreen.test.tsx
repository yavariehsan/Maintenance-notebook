import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { TroubleshootingGuideScreen } from './TroubleshootingGuideScreen'
import {
  useTroubleshootingEquipment,
  useTroubleshootingFailureModes,
  useTroubleshootingGuide,
  useTroubleshootingStatus,
} from '@/lib/hooks/use-troubleshooting'
import type {
  TroubleshootingEquipment,
  TroubleshootingFailureMode,
  TroubleshootingGuide,
  TroubleshootingStatus,
} from '@/lib/api/troubleshooting'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/lib/hooks/use-troubleshooting', () => ({
  useTroubleshootingStatus: vi.fn(),
  useTroubleshootingEquipment: vi.fn(),
  useTroubleshootingEquipmentDetail: vi.fn(),
  useTroubleshootingFailureModes: vi.fn(),
  useTroubleshootingGuide: vi.fn(),
  useTroubleshootingCauses: vi.fn(),
  useTroubleshootingEvidence: vi.fn(),
}))

const mockStatus = vi.mocked(useTroubleshootingStatus)
const mockEquipment = vi.mocked(useTroubleshootingEquipment)
const mockModes = vi.mocked(useTroubleshootingFailureModes)
const mockGuide = vi.mocked(useTroubleshootingGuide)

const available: TroubleshootingStatus = {
  state: 'available',
  schema_version: '1',
  expected_schema_version: '1',
  equipment_count: 1,
  message: 'ok',
}

const equipment: TroubleshootingEquipment[] = [
  {
    code: 'B104',
    name: 'mill',
    manufacturer: null,
    model: null,
    record_count: 3,
    failure_mode_count: 1,
  },
]

const modes: TroubleshootingFailureMode[] = [
  { id: 'fm-1', label: 'روشن نشدن', record_count: 2, cause_count: 1 },
]

const guide: TroubleshootingGuide = {
  equipment_code: 'B104',
  failure_mode_id: 'fm-1',
  failure_mode_label: 'روشن نشدن',
  symptom_summary: 'دستگاه روشن نمی‌شود',
  causes: [
    {
      id: 'cause-1',
      label: 'خرابی منبع تغذیه',
      kinds: ['explicitly_recorded'],
      support_percent: 66.7,
      evidence_count: 2,
      weighted_evidence: 2,
      denominator: 3,
      calculation_method: 'weighted_share',
      similarity_score: null,
      similarity_basis: null,
      confidence: 0.5,
      probability: 0.67,
      rank: 1,
      actions: [
        {
          id: 'a-1',
          category: null,
          role: 'corrective',
          action_text: 'منبع تغذیه تعویض شد',
          source_record_ids: ['k-B-1'],
          frequency: 1,
        },
      ],
      evidence: [
        {
          id: 'e-1',
          record_id: 'k-B-1',
          equipment_code: 'B104',
          relevance_basis: 'exact',
          relevance_detail: null,
          weight: 1,
          symptom_text: 'روشن نشدن',
          repair_description: 'تعویض شد',
        },
      ],
    },
  ],
  sections: [],
  safety_notes: [{ note_text: 'برق را قطع کنید', source_record_ids: [], cause_ids: [] }],
  warnings: ['insufficient_historical_repair_evidence'],
}

function mockAll(overrides: {
  status?: TroubleshootingStatus
  equipmentData?: TroubleshootingEquipment[] | undefined
  modesData?: TroubleshootingFailureMode[] | undefined
  guideData?: TroubleshootingGuide | undefined
} = {}) {
  mockStatus.mockReturnValue({
    data: overrides.status ?? available,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useTroubleshootingStatus>)
  mockEquipment.mockReturnValue({
    data: overrides.equipmentData ?? equipment,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useTroubleshootingEquipment>)
  mockModes.mockReturnValue({
    data: overrides.modesData,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useTroubleshootingFailureModes>)
  mockGuide.mockReturnValue({
    data: overrides.guideData,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useTroubleshootingGuide>)
}

describe('TroubleshootingGuideScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Radix Select calls scrollIntoView, which jsdom does not implement.
    window.HTMLElement.prototype.scrollIntoView = vi.fn()
  })

  it('renders the guide title and description', () => {
    mockAll()
    render(<TroubleshootingGuideScreen />)
    expect(screen.getByText('troubleshootingGuide.title')).toBeInTheDocument()
    expect(screen.getByText('troubleshootingGuide.selectEquipmentTitle')).toBeInTheDocument()
  })

  it('shows the unavailable state when no database exists', () => {
    mockAll({ status: { ...available, state: 'missing' } })
    render(<TroubleshootingGuideScreen />)
    expect(
      screen.getByText('troubleshootingGuide.databaseUnavailableTitle'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('troubleshootingGuide.selectEquipmentTitle'),
    ).not.toBeInTheDocument()
  })

  it('shows the incompatible state distinctly', () => {
    mockAll({ status: { ...available, state: 'incompatible' } })
    render(<TroubleshootingGuideScreen />)
    expect(
      screen.getByText('troubleshootingGuide.databaseIncompatibleDesc'),
    ).toBeInTheDocument()
  })

  it('shows the empty-equipment state', () => {
    mockAll({ equipmentData: [] })
    render(<TroubleshootingGuideScreen />)
    expect(screen.getByText('troubleshootingGuide.noEquipmentTitle')).toBeInTheDocument()
  })

  it('walks equipment to failure mode to guide with distinct metrics', async () => {
    mockAll({ modesData: modes, guideData: guide })
    render(<TroubleshootingGuideScreen />)

    fireEvent.click(screen.getByRole('combobox'))
    fireEvent.click(await screen.findByRole('option', { name: /B104/ }))
    await waitFor(() => {
      expect(
        screen.getByText('troubleshootingGuide.selectFailureModeTitle'),
      ).toBeInTheDocument()
    })

    const boxes = screen.getAllByRole('combobox')
    fireEvent.click(boxes[boxes.length - 1])
    fireEvent.click(await screen.findByRole('option', { name: /روشن نشدن/ }))
    await waitFor(() => {
      expect(screen.getByText('troubleshootingGuide.guideTitle')).toBeInTheDocument()
    })

    // Precomputed values stay distinct: support (percent) vs probability
    // and confidence (fractions) vs evidence count.
    expect(screen.getByText(/66\.7/)).toBeInTheDocument()
    expect(screen.getByText(/0\.67/)).toBeInTheDocument()
    expect(screen.getByText(/0\.50/)).toBeInTheDocument()
    expect(screen.getByText(/خرابی منبع تغذیه/)).toBeInTheDocument()
    expect(screen.getByText('منبع تغذیه تعویض شد')).toBeInTheDocument()
    expect(screen.getByText('برق را قطع کنید')).toBeInTheDocument()
    // The insufficiency warning is surfaced, never hidden.
    expect(
      screen.getByText('troubleshootingGuide.insufficientEvidence'),
    ).toBeInTheDocument()
  })

  it('shows the no-failure-modes state for the selected equipment', async () => {
    mockAll({ modesData: [] })
    render(<TroubleshootingGuideScreen />)

    fireEvent.click(screen.getByRole('combobox'))
    fireEvent.click(await screen.findByRole('option', { name: /B104/ }))
    await waitFor(() => {
      expect(
        screen.getByText('troubleshootingGuide.noFailureModesTitle'),
      ).toBeInTheDocument()
    })
  })
})
