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

vi.mock('@/lib/hooks/use-repair-reports', () => ({
  useRepairReports: vi.fn(),
  useRepairReport: vi.fn(),
  useRepairReportPreview: vi.fn(),
  useRepairReportActions: vi.fn(),
  useRepairAnalysisRuns: vi.fn(),
  useUploadRepairReport: vi.fn(),
  useStartRepairAnalysis: vi.fn(),
  useStartSingleReportAnalysis: vi.fn(),
  useDeleteRepairReport: vi.fn(),
}))

vi.mock('@/lib/hooks/use-llm-knowledge', () => ({
  useLLMBuilds: vi.fn(),
  useLLMBuild: vi.fn(),
  useLLMGuide: vi.fn(),
  useStartLLMBuild: vi.fn(),
}))

import {
  useRepairAnalysisRuns,
  useRepairReports,
} from '@/lib/hooks/use-repair-reports'
import {
  useLLMBuilds,
  useLLMGuide,
} from '@/lib/hooks/use-llm-knowledge'
import type {
  RepairAnalysisRun,
  RepairReport,
} from '@/lib/api/repair-reports'
import type {
  LLMGuide,
  LLMKnowledgeBuild,
} from '@/lib/api/llm-knowledge'

const mockSourceReports = vi.mocked(useRepairReports)
const mockAnalysisRuns = vi.mocked(useRepairAnalysisRuns)
const mockLLMBuilds = vi.mocked(useLLMBuilds)
const mockLLMGuide = vi.mocked(useLLMGuide)

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
          guide_instruction: null,
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
    {
      id: 'cause-2',
      label: 'شل بودن سیم‌کشی',
      kinds: ['explicitly_recorded'],
      support_percent: 33.3,
      evidence_count: 1,
      weighted_evidence: 1,
      denominator: 3,
      calculation_method: 'weighted_share',
      similarity_score: null,
      similarity_basis: null,
      confidence: 0.3,
      probability: 0.33,
      rank: 2,
      actions: [
        {
          id: 'a-1-dup',
          category: null,
          role: 'corrective',
          action_text: 'منبع تغذیه تعویض شد',
          source_record_ids: ['k-B-2'],
          frequency: 1,
          guide_instruction: null,
        },
        {
          id: 'a-2',
          category: null,
          role: 'diagnostic',
          action_text: 'سیم‌کشی بررسی شد',
          source_record_ids: ['k-B-2'],
          frequency: 3,
          guide_instruction: null,
        },
      ],
      evidence: [],
    },
  ],
  sections: [
    {
      section: 'method',
      title: 'How these numbers were produced',
      position: 10,
      body: 'Support percentages are shares of similarity-weighted evidence.',
    },
  ],
  safety_notes: [{ note_text: 'برق را قطع کنید', source_record_ids: [], cause_ids: [] }],
  warnings: ['insufficient_historical_repair_evidence'],
}

function mockAll(overrides: {
  status?: TroubleshootingStatus
  equipmentData?: TroubleshootingEquipment[] | undefined
  modesData?: TroubleshootingFailureMode[] | undefined
  guideData?: TroubleshootingGuide | undefined
  sourceReports?: RepairReport[] | undefined
  analysisRuns?: RepairAnalysisRun[] | undefined
  llmBuilds?: LLMKnowledgeBuild[] | undefined
  llmGuideData?: LLMGuide | undefined
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
  mockSourceReports.mockReturnValue({
    data: overrides.sourceReports ?? [],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useRepairReports>)
  mockAnalysisRuns.mockReturnValue({
    data: overrides.analysisRuns ?? [],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useRepairAnalysisRuns>)
  mockLLMBuilds.mockReturnValue({
    data: overrides.llmBuilds ?? [],
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useLLMBuilds>)
  mockLLMGuide.mockReturnValue({
    data: overrides.llmGuideData,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useLLMGuide>)
}

const sourceA: RepairReport = {
  id: 'repair_report:aaa',
  filename: 'cmms.xlsx',
  size_bytes: 1024,
  sheet: 'Sheet1',
  column_count: 9,
  data_rows: 4,
  analysis_state: 'completed',
  last_run_id: 'repair_analysis_run:runA',
  last_error: null,
  created: '2026-09-26T00:00:00',
  updated: '2026-09-26T00:00:00',
}

const sourceB: RepairReport = {
  ...sourceA,
  id: 'repair_report:bbb',
  data_rows: 7,
  created: '2026-09-27T00:00:00',
  last_run_id: 'repair_analysis_run:runB',
}

function completedRun(id: string, reportIds: string[]): RepairAnalysisRun {
  return {
    id,
    report_ids: reportIds,
    manifest: [],
    status: 'completed',
    command_id: 'command:1',
    error: null,
    record_count: 4,
    equipment_count: 1,
    failure_mode_count: 1,
    guide_count: 1,
    created: '2026-09-27T00:00:00',
    started_at: null,
    finished_at: '2026-09-27T00:01:00',
  }
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

  it('renders equipment options using only the equipment code', async () => {
    mockAll({ modesData: [] })
    render(<TroubleshootingGuideScreen />)

    fireEvent.click(screen.getByRole('combobox'))
    const option = await screen.findByRole('option', { name: 'B104' })
    // Only the code: no name, manufacturer, model, or counts in the label.
    expect(option.textContent).toBe('B104')
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
    expect(screen.getAllByText('منبع تغذیه تعویض شد').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('برق را قطع کنید')).toBeInTheDocument()
    // The insufficiency warning is surfaced, never hidden.
    expect(
      screen.getByText('troubleshootingGuide.insufficientEvidence'),
    ).toBeInTheDocument()
  })

  it('presents a unified repair procedure, not just cause cards', async () => {
    mockAll({ modesData: modes, guideData: guide })
    render(<TroubleshootingGuideScreen />)

    fireEvent.click(screen.getByRole('combobox'))
    fireEvent.click(await screen.findByRole('option', { name: 'B104' }))
    await waitFor(() => {
      expect(
        screen.getByText('troubleshootingGuide.selectFailureModeTitle'),
      ).toBeInTheDocument()
    })
    const boxes = screen.getAllByRole('combobox')
    fireEvent.click(boxes[boxes.length - 1])
    fireEvent.click(await screen.findByRole('option', { name: /روشن نشدن/ }))
    await waitFor(() => {
      expect(
        screen.getByText('troubleshootingGuide.recommendedActionsTitle'),
      ).toBeInTheDocument()
    })

    // Both causes remain visible as components of the guide...
    expect(screen.getByText(/خرابی منبع تغذیه/)).toBeInTheDocument()
    expect(screen.getByText(/شل بودن سیم‌کشی/)).toBeInTheDocument()
    // ...while the shared action is deduplicated in the unified procedure.
    const unified = screen.getByTestId('recommended-actions')
    expect(unified.textContent).toMatch(/سیم‌کشی بررسی شد/)
    const occurrences = (unified.textContent?.match(/منبع تغذیه تعویض شد/g) ?? []).length
    expect(occurrences).toBe(1)
    // Roles and provenance travel with the unified actions.
    expect(unified.textContent).toMatch(/diagnostic/)
    expect(unified.textContent).toMatch(/k-B-1/)
    // Methodology footnote from the precomputed method section.
    expect(screen.getByText(/similarity-weighted evidence/)).toBeInTheDocument()
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

  it('lists uploaded sources with ID-stable values and duplicate context', async () => {
    mockAll({
      modesData: [],
      sourceReports: [sourceA, sourceB],
      analysisRuns: [completedRun('repair_analysis_run:runB', ['repair_report:bbb'])],
    })
    render(<TroubleshootingGuideScreen />)

    expect(screen.getByText('troubleshootingGuide.selectSourceTitle')).toBeInTheDocument()
    // The backing run names its source (mock t renders the key); both
    // same-named files stay listed once the selector opens.
    expect(screen.getByText('troubleshootingGuide.sourceBacksDb')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('combobox')[0])
    const options = await screen.findAllByRole('option')
    expect(options).toHaveLength(2)
    // Duplicate filenames remain distinguishable (rows, date, short ID).
    expect(options[0].textContent).toContain('cmms.xlsx')
    expect(options[1].textContent).toContain('cmms.xlsx')
    expect(options[0].textContent).not.toBe(options[1].textContent)
  })

  it('hides guides when the selected source is not the backing source', async () => {
    mockAll({
      modesData: modes,
      guideData: guide,
      sourceReports: [sourceA, sourceB],
      analysisRuns: [completedRun('repair_analysis_run:runB', ['repair_report:bbb'])],
    })
    render(<TroubleshootingGuideScreen />)

    // Select source A while the database was generated from source B.
    fireEvent.click(screen.getAllByRole('combobox')[0])
    fireEvent.click(await screen.findByRole('option', { name: /2026-09-26/ }))
    await waitFor(() => {
      expect(
        screen.getByText('troubleshootingGuide.sourceMismatchTitle'),
      ).toBeInTheDocument()
    })
    // No guides from source B leak through.
    expect(screen.queryByText('troubleshootingGuide.selectEquipmentTitle')).not.toBeInTheDocument()
  })

  it('warns without remapping when the backing source was deleted', () => {
    mockAll({
      modesData: [],
      sourceReports: [sourceA],
      analysisRuns: [completedRun('repair_analysis_run:runX', ['repair_report:gone'])],
    })
    render(<TroubleshootingGuideScreen />)

    expect(screen.getByText('troubleshootingGuide.sourceDeletedWarning')).toBeInTheDocument()
    // The deleted ID never resolves to the surviving same-named file:
    // no backing-source line is rendered for the missing ID.
    expect(screen.queryByText('troubleshootingGuide.sourceBacksDb')).not.toBeInTheDocument()
  })

  it('shows the no-sources empty state when nothing was uploaded', () => {
    mockAll({ modesData: [], sourceReports: [], analysisRuns: [] })
    render(<TroubleshootingGuideScreen />)
    expect(screen.getByText('troubleshootingGuide.noSourcesTitle')).toBeInTheDocument()
  })

  it('renders the synthesized instruction with its recorded-action link', async () => {
    const instructed = JSON.parse(JSON.stringify(guide)) as typeof guide
    instructed.causes[0].actions[0] = {
      ...instructed.causes[0].actions[0],
      guide_instruction: 'در صورت عدم تعویض پالت، سوئیچ بررسی و در صورت لزوم تنظیم گردد.',
    }
    mockAll({ modesData: modes, guideData: instructed })
    render(<TroubleshootingGuideScreen />)

    fireEvent.click(screen.getByRole('combobox'))
    fireEvent.click(await screen.findByRole('option', { name: 'B104' }))
    const boxes = screen.getAllByRole('combobox')
    fireEvent.click(boxes[boxes.length - 1])
    fireEvent.click(await screen.findByRole('option', { name: /روشن نشدن/ }))
    await waitFor(() => {
      expect(
        screen.getByText('troubleshootingGuide.recommendedActionsTitle'),
      ).toBeInTheDocument()
    })
    const unified = screen.getByTestId('recommended-actions')
    expect(unified.textContent).toMatch(/در صورت عدم تعویض پالت/)
    // Original recorded action stays linked beneath the instruction
    // (mock t renders the basedOn key) with source record refs intact.
    expect(unified.textContent).toMatch(/troubleshootingGuide\.basedOnLabel/)
    expect(unified.textContent).toMatch(/k-B-1/)
  })

  // --- M12: Knowledge Source selector (Text Mining vs LLM) --------------------

  const llmBuild: LLMKnowledgeBuild = {
    id: 'llm_knowledge_build:12',
    source_report_ids: ['repair_report:aaa', 'repair_report:bbb'],
    manifest: [
      { report_id: 'repair_report:aaa', filename: 'cmms.xlsx', analysis_key: 'k1' },
      { report_id: 'repair_report:bbb', filename: 'cmms.xlsx', analysis_key: 'k2' },
    ],
    status: 'completed',
    command_id: 'command:llm1',
    model: 'model:chat',
    prompt_version: 'm12-v1',
    error: null,
    warnings: [],
    record_count: 2,
    failed_record_count: 0,
    created: '2026-09-28T10:00:00',
    started_at: null,
    finished_at: '2026-09-28T10:01:00',
  }

  const llmGuideData: LLMGuide = {
    knowledge_source: 'LLM',
    build_id: 'llm_knowledge_build:12',
    model: 'model:chat',
    prompt_version: 'm12-v1',
    source_report_id: 'repair_report:aaa',
    source_filename: 'cmms.xlsx',
    source_deleted: false,
    final_guides: [],
    records: [
      {
        id: 'llm_knowledge_record:1',
        build_id: 'llm_knowledge_build:12',
        source_report_id: 'repair_report:aaa',
        source_record_id: 'k1-LLMROW-Sheet1-2',
        source_text: 'عیب: لرزش بستر',
        symptom: 'لرزش بستر',
        findings: [
          { text: 'سایش گاید', basis: 'DATA_SUPPORTED', source_quote: 'سایش' },
        ],
        candidate_causes: [
          { text: 'خرابی گایدها', basis: 'LLM_INFERRED', source_quote: null },
        ],
        diagnostic_steps: [],
        corrective_actions: [],
        verification_steps: [
          { text: 'تست شد', basis: 'DATA_SUPPORTED', source_quote: 'تست شد' },
        ],
        post_repair_events: [],
        record_error: null,
        created: '2026-09-28T10:00:00',
      },
    ],
    warnings: [],
  }

  function switchToLLM() {
    fireEvent.click(screen.getByRole('button', { name: 'troubleshootingGuide.knowledgeSourceLLM' }))
  }

  it('offers Text Mining and LLM sources with mining as default', () => {
    mockAll({ modesData: [] })
    render(<TroubleshootingGuideScreen />)
    expect(
      screen.getByRole('button', { name: 'troubleshootingGuide.knowledgeSourceMining' }),
    ).toHaveAttribute('aria-pressed', 'true')
    expect(
      screen.getByRole('button', { name: 'troubleshootingGuide.knowledgeSourceLLM' }),
    ).toHaveAttribute('aria-pressed', 'false')
    // Mining behavior unchanged: no LLM content leaks in.
    expect(screen.queryByTestId('llm-guide')).not.toBeInTheDocument()
    expect(screen.getByText('troubleshootingGuide.selectEquipmentTitle')).toBeInTheDocument()
  })

  it('shows the no-builds empty state when no LLM build exists', async () => {
    mockAll({ modesData: [], llmBuilds: [] })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()
    expect(screen.getByText('troubleshootingGuide.noLLMBuildsTitle')).toBeInTheDocument()
  })

  it('selects build and source, then shows provenance with historical/inferred split', async () => {
    mockAll({
      modesData: [],
      sourceReports: [sourceA, sourceB],
      llmBuilds: [llmBuild],
      llmGuideData,
    })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()

    // Source options come from the build manifest: duplicate filenames
    // stay distinguishable by stable short ID.
    const boxes = screen.getAllByRole('combobox')
    fireEvent.click(boxes[boxes.length - 1])
    const options = await screen.findAllByRole('option')
    expect(options).toHaveLength(2)
    expect(options[0].textContent).toContain('cmms.xlsx')
    expect(options[0].textContent).not.toBe(options[1].textContent)
    fireEvent.click(options[0])

    await waitFor(() => {
      expect(screen.getByTestId('llm-guide')).toBeInTheDocument()
    })
    const panel = screen.getByTestId('llm-guide')
    // Provenance header: source, build, model, prompt version, report ID.
    expect(panel.textContent).toMatch(/troubleshootingGuide\.knowledgeSourceLLM/)
    expect(panel.textContent).toMatch(/model:chat/)
    expect(panel.textContent).toMatch(/m12-v1/)
    expect(panel.textContent).toMatch(/repair_report:aaa/)
    // Historical evidence vs LLM interpretation stay visually distinct.
    expect(panel.textContent).toMatch(/troubleshootingGuide\.llmHistoricalTitle/)
    expect(panel.textContent).toMatch(/troubleshootingGuide\.llmInferredTitle/)
    expect(panel.textContent).toMatch(/troubleshootingGuide\.llmSupportedBadge/)
    expect(panel.textContent).toMatch(/troubleshootingGuide\.llmInferredBadge/)
    expect(panel.textContent).toMatch(/سایش گاید/)
    expect(panel.textContent).toMatch(/خرابی گایدها/)
    // Verbatim source text is preserved, never rewritten.
    expect(panel.textContent).toMatch(/عیب: لرزش بستر/)
    // Mining guide is never rendered alongside.
    expect(screen.queryByText('troubleshootingGuide.causesTitle')).not.toBeInTheDocument()
  })

  it('shows the deleted-source state without remapping', async () => {
    mockAll({
      modesData: [],
      sourceReports: [sourceB],
      llmBuilds: [llmBuild],
      llmGuideData: {
        ...llmGuideData,
        source_filename: null,
        source_deleted: true,
        records: [],
        warnings: ['source_deleted'],
      },
    })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()

    const boxes = screen.getAllByRole('combobox')
    fireEvent.click(boxes[boxes.length - 1])
    const options = await screen.findAllByRole('option')
    // The deleted manifest entry is marked unavailable (✕), not remapped
    // to the surviving same-named file.
    expect(options.some((option) => option.textContent?.includes('✕'))).toBe(true)
    fireEvent.click(options[0])
    await waitFor(() => {
      expect(
        screen.getByText('troubleshootingGuide.llmSourceDeletedTitle'),
      ).toBeInTheDocument()
    })
  })

  it('shows the empty-records state when the build has nothing for the source', async () => {
    mockAll({
      modesData: [],
      sourceReports: [sourceA, sourceB],
      llmBuilds: [llmBuild],
      llmGuideData: {
        ...llmGuideData,
        records: [],
        warnings: ['no_records_for_source'],
      },
    })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()

    const boxes = screen.getAllByRole('combobox')
    fireEvent.click(boxes[boxes.length - 1])
    fireEvent.click((await screen.findAllByRole('option'))[0])
    await waitFor(() => {
      expect(
        screen.getByText('troubleshootingGuide.llmNoRecordsTitle'),
      ).toBeInTheDocument()
    })
  })

  it('renders the LLM branch while the mining database is unavailable', async () => {
    mockAll({
      status: { ...available, state: 'missing' },
      modesData: [],
      sourceReports: [sourceA, sourceB],
      llmBuilds: [llmBuild],
      llmGuideData,
    })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()

    const boxes = screen.getAllByRole('combobox')
    fireEvent.click(boxes[boxes.length - 1])
    fireEvent.click((await screen.findAllByRole('option'))[0])
    await waitFor(() => {
      expect(screen.getByTestId('llm-guide')).toBeInTheDocument()
    })
    // The mining outage never leaks into the independent LLM output.
    expect(
      screen.queryByText('troubleshootingGuide.databaseUnavailableTitle'),
    ).not.toBeInTheDocument()
  })

  it('keeps the mining unavailable state for the mining method', () => {
    mockAll({
      status: { ...available, state: 'missing' },
      modesData: [],
      llmBuilds: [llmBuild],
    })
    render(<TroubleshootingGuideScreen />)
    expect(
      screen.getByText('troubleshootingGuide.databaseUnavailableTitle'),
    ).toBeInTheDocument()
    expect(screen.queryByTestId('llm-guide')).not.toBeInTheDocument()
  })

  it('fetches the guide for the auto-selected newest finished build', async () => {
    mockAll({
      modesData: [],
      sourceReports: [sourceA, sourceB],
      llmBuilds: [llmBuild],
      llmGuideData,
    })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()

    // No explicit build pick: the newest finished build is the default.
    // Selecting only the source must fetch (build, source), not stall.
    const boxes = screen.getAllByRole('combobox')
    fireEvent.click(boxes[boxes.length - 1])
    fireEvent.click((await screen.findAllByRole('option'))[0])
    await waitFor(() => {
      expect(mockLLMGuide).toHaveBeenCalledWith(
        'llm_knowledge_build:12',
        'repair_report:aaa',
      )
    })
  })

  it('shows the failed build error once the failed build is selected', async () => {
    const failedBuild: LLMKnowledgeBuild = {
      ...llmBuild,
      id: 'llm_knowledge_build:0tsuvd',
      status: 'failed',
      error: 'LLM knowledge build has no report manifest.',
      record_count: 0,
      failed_record_count: 0,
    }
    mockAll({
      modesData: [],
      sourceReports: [sourceA, sourceB],
      llmBuilds: [failedBuild],
    })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()

    // Explicitly pick the failed build (it is never the auto default).
    fireEvent.click(screen.getByRole('combobox'))
    fireEvent.click(await screen.findByRole('option', { name: /failed/ }))
    await waitFor(() => {
      expect(
        screen.getByText(/LLM knowledge build has no report manifest\./),
      ).toBeInTheDocument()
    })
  })

  const finalGuideA = {
    synthesis_id: 'llm_stage_b_guide:s1',
    build_id: 'llm_knowledge_build:12',
    equipment: 'B138',
    failure_mode: 'تعویض ابزار',
    guide_markdown: '# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی\n\nمتن راهنمای یک',
    record_count: 2,
    batch_ids: ['k1-LLMBATCH-aa-000'],
    source_record_ids: ['k1-LLMROW-Sheet1-2'],
    model: 'model:chat',
    prompt_version: 'stageab-v1',
    math_warnings: [],
  }

  const finalGuideB = {
    ...finalGuideA,
    synthesis_id: 'llm_stage_b_guide:s2',
    failure_mode: 'خرابی اسپیندل',
    guide_markdown: '# ترتیب پیشنهادی تعمیرکار؛ نسخه عملیاتی\n\nمتن راهنمای دو',
  }

  async function openLlmGuide() {
    const boxes = screen.getAllByRole('combobox')
    fireEvent.click(boxes[boxes.length - 1])
    fireEvent.click((await screen.findAllByRole('option'))[0])
    await waitFor(() => {
      expect(screen.getByTestId('llm-guide')).toBeInTheDocument()
    })
  }

  it('renders the final Stage B guide as primary, not the extraction records', async () => {
    mockAll({
      modesData: [],
      sourceReports: [sourceA, sourceB],
      llmBuilds: [llmBuild],
      llmGuideData: { ...llmGuideData, final_guides: [finalGuideA] },
    })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()
    await openLlmGuide()
    // Final markdown is the primary output.
    expect(screen.getByTestId('llm-final-guide')).toBeInTheDocument()
    expect(screen.getByText(/متن راهنمای یک/)).toBeInTheDocument()
    // Obsolete per-record extraction cards are not primary.
    expect(
      screen.queryByText('troubleshootingGuide.llmHistoricalTitle'),
    ).not.toBeInTheDocument()
  })

  it('switches between failure-mode guides via the picker', async () => {
    mockAll({
      modesData: [],
      sourceReports: [sourceA, sourceB],
      llmBuilds: [llmBuild],
      llmGuideData: { ...llmGuideData, final_guides: [finalGuideA, finalGuideB] },
    })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()
    await openLlmGuide()
    expect(screen.getByText(/متن راهنمای یک/)).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('llm-final-guide-picker'))
    fireEvent.click(await screen.findByRole('option', { name: /خرابی اسپیندل/ }))
    await waitFor(() => {
      expect(screen.getByText(/متن راهنمای دو/)).toBeInTheDocument()
    })
    expect(screen.queryByText(/متن راهنمای یک/)).not.toBeInTheDocument()
  })

  it('opens the final guide read-only from the guide query', async () => {
    mockAll({
      modesData: [],
      sourceReports: [sourceA, sourceB],
      llmBuilds: [llmBuild],
      llmGuideData: { ...llmGuideData, final_guides: [finalGuideA] },
    })
    render(<TroubleshootingGuideScreen />)
    await switchToLLM()
    await openLlmGuide()
    // Data flows from the read query; the screen holds no generation trigger.
    expect(mockLLMGuide).toHaveBeenCalledWith(
      'llm_knowledge_build:12',
      'repair_report:aaa',
    )
    expect(screen.getByText(/متن راهنمای یک/)).toBeInTheDocument()
    expect(
      screen.queryByText('llmKnowledge.startBuildButton'),
    ).not.toBeInTheDocument()
  })
})
