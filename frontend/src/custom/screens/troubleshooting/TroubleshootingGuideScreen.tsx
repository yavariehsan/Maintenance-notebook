'use client'

import { useMemo, useState } from 'react'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { AlertCircle, AlertTriangle, LifeBuoy, RefreshCw } from 'lucide-react'
import {
  useTroubleshootingEquipment,
  useTroubleshootingFailureModes,
  useTroubleshootingGuide,
  useTroubleshootingStatus,
} from '@/lib/hooks/use-troubleshooting'
import {
  useRepairAnalysisRuns,
  useRepairReports,
} from '@/lib/hooks/use-repair-reports'
import {
  useLLMBuilds,
  useLLMGuide,
} from '@/lib/hooks/use-llm-knowledge'
import type { LLMKnowledgeBuild, LLMGuide } from '@/lib/api/llm-knowledge'
import { isTroubleshootingAvailable } from '@/lib/api/troubleshooting'
import type {
  TroubleshootingCause,
  TroubleshootingCauseAction,
} from '@/lib/api/troubleshooting'
import { useTranslation } from '@/lib/hooks/use-translation'

/**
 * Downstream troubleshooting guide screen (پردازش → راهنمای تعمیر).
 * Equipment → failure mode → precomputed guide, read exclusively through
 * the Milestone 5 hooks (no mining, no LLM, no client-side scoring).
 * Support (0–100%), probability (0–1 share) and confidence (0–1) are
 * rendered as distinct labeled values exactly as precomputed.
 */
function formatSupport(value: number | null): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(1)}٪`
}

function formatFraction(value: number | null): string {
  if (value === null || value === undefined) return '—'
  return value.toFixed(2)
}

function formatCauseOption(cause: TroubleshootingCause): string {
  return `#${cause.rank} — ${cause.label}`
}

const INSUFFICIENT_EVIDENCE_WARNING = 'insufficient_historical_repair_evidence'

export function TroubleshootingGuideScreen() {
  const { t } = useTranslation()
  const [knowledgeSource, setKnowledgeSource] = useState<'mining' | 'llm'>('mining')
  const [selectedCode, setSelectedCode] = useState<string>('')
  const [selectedModeId, setSelectedModeId] = useState<string>('')
  const [selectedSourceId, setSelectedSourceId] = useState<string>('')
  const [selectedBuildId, setSelectedBuildId] = useState<string>('')
  const [selectedLlmSourceId, setSelectedLlmSourceId] = useState<string>('')

  const {
    data: status,
    isLoading: statusLoading,
    isError: statusError,
    refetch: refetchStatus,
  } = useTroubleshootingStatus()
  const available = isTroubleshootingAvailable(status ?? null)

  const {
    data: equipment,
    isLoading: equipmentLoading,
    isError: equipmentError,
    refetch: refetchEquipment,
  } = useTroubleshootingEquipment()
  const {
    data: failureModes,
    isLoading: modesLoading,
    isError: modesError,
    refetch: refetchModes,
  } = useTroubleshootingFailureModes(available ? selectedCode || null : null)
  const {
    data: guide,
    isLoading: guideLoading,
    isError: guideError,
    refetch: refetchGuide,
  } = useTroubleshootingGuide(
    available ? selectedCode || null : null,
    available ? selectedModeId || null : null,
  )

  /**
   * Source-report chain (M11C-6R2 Part D): which uploaded repair report(s)
   * the current knowledge database was generated from. Report identity is
   * always the stable record ID — never the filename alone — so duplicate
   * filenames stay distinguishable and deleted sources can never silently
   * remap to another same-named file.
   */
  const { data: sourceReports } = useRepairReports()
  const { data: analysisRuns } = useRepairAnalysisRuns()
  const { data: llmBuilds } = useLLMBuilds()
  const {
    data: llmGuide,
    isLoading: llmGuideLoading,
    isError: llmGuideError,
    refetch: refetchLlmGuide,
  } = useLLMGuide(
    knowledgeSource === 'llm' ? selectedBuildId || null : null,
    knowledgeSource === 'llm' ? selectedLlmSourceId || null : null,
  )

  const latestCompletedRun = useMemo(() => {
    const completed = (analysisRuns ?? []).filter((run) => run.status === 'completed')
    return (
      [...completed].sort((a, b) => (b.created ?? '').localeCompare(a.created ?? ''))[0] ??
      null
    )
  }, [analysisRuns])
  const backingReportIds = useMemo(
    () => latestCompletedRun?.report_ids ?? [],
    [latestCompletedRun],
  )
  const backingReports = useMemo(
    () => (sourceReports ?? []).filter((report) => backingReportIds.includes(report.id)),
    [sourceReports, backingReportIds],
  )
  const deletedBackingIds = useMemo(
    () =>
      backingReportIds.filter(
        (id) => !(sourceReports ?? []).some((report) => report.id === id),
      ),
    [sourceReports, backingReportIds],
  )
  // A selected source gates guide browsing only with positive run
  // evidence: when the database's backing run is known and the selection
  // is not in it, guides are hidden (mismatch) instead of showing
  // another source's knowledge.
  const sourceMismatch =
    latestCompletedRun !== null &&
    selectedSourceId !== '' &&
    !backingReportIds.includes(selectedSourceId)

  /**
   * LLM knowledge-source branch (M12): builds coexist; the effective
   * build defaults to the newest finished (completed, then partial)
   * build until the user picks explicitly. Source options come from
   * the build manifest (audit-stable filenames), never remapped:
   * a deleted backing report keeps its stable ID with an unavailable
   * marker.
   */
  const finishedLlmBuilds = useMemo(
    () =>
      (llmBuilds ?? [])
        .filter((build) => build.status === 'completed' || build.status === 'partial')
        .sort((a, b) => (b.created ?? '').localeCompare(a.created ?? '')),
    [llmBuilds],
  )
  const effectiveBuild: LLMKnowledgeBuild | null = useMemo(() => {
    const explicit = (llmBuilds ?? []).find((build) => build.id === selectedBuildId) ?? null
    return explicit ?? finishedLlmBuilds[0] ?? null
  }, [llmBuilds, selectedBuildId, finishedLlmBuilds])
  const llmManifestSources = useMemo(
    () => effectiveBuild?.manifest ?? [],
    [effectiveBuild],
  )
  const llmSourceDeleted = (reportId: string) =>
    !(sourceReports ?? []).some((report) => report.id === reportId)

  const handleSelectCode = (code: string) => {
    setSelectedCode(code)
    setSelectedModeId('')
  }

  const handleSelectKnowledgeSource = (source: 'mining' | 'llm') => {
    setKnowledgeSource(source)
    setSelectedCode('')
    setSelectedModeId('')
    setSelectedSourceId('')
    setSelectedBuildId('')
    setSelectedLlmSourceId('')
  }

  /**
   * Unified repair procedure composed for display only: distinct historical
   * actions across all candidate causes, first-seen wins, ordered by cause
   * rank then recorded frequency. Roles, frequencies and source record IDs
   * are precomputed values passed through unchanged — no new scoring.
   */
  const recommendedActions = useMemo(() => {
    if (!guide) return []
    const seen = new Map<string, TroubleshootingCauseAction & { causeRank: number }>()
    for (const cause of guide.causes) {
      for (const action of cause.actions) {
        const key = (action.action_text || '').trim()
        if (!key || seen.has(key)) continue
        seen.set(key, { ...action, causeRank: cause.rank })
      }
    }
    return [...seen.values()].sort(
      (a, b) => a.causeRank - b.causeRank || (b.frequency ?? 0) - (a.frequency ?? 0),
    )
  }, [guide])

  const methodSection = useMemo(
    () => guide?.sections.find((section) => section.section === 'method') ?? null,
    [guide],
  )

  const renderCause = (cause: TroubleshootingCause) => (
    <Card key={cause.id}>
      <CardHeader>
        <CardTitle className="text-sm font-medium">
          {formatCauseOption(cause)}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="font-mono text-[11px]">
            {t('troubleshootingGuide.supportLabel')}: {formatSupport(cause.support_percent)}
          </Badge>
          <Badge variant="secondary" className="font-mono text-[11px]">
            {t('troubleshootingGuide.probabilityLabel')}: {formatFraction(cause.probability)}
          </Badge>
          <Badge variant="secondary" className="font-mono text-[11px]">
            {t('troubleshootingGuide.confidenceLabel')}: {formatFraction(cause.confidence)}
          </Badge>
          <Badge variant="outline" className="font-mono text-[11px]">
            {t('troubleshootingGuide.evidenceCountLabel', { count: cause.evidence_count })}
          </Badge>
        </div>
        {cause.kinds.length > 0 && (
          <p className="text-xs text-muted-foreground font-mono">
            {cause.kinds.join(' · ')}
          </p>
        )}
        <div className="space-y-2">
          <h4 className="text-sm font-medium">{t('troubleshootingGuide.actionsTitle')}</h4>
          {cause.actions.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t('troubleshootingGuide.noActions')}</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {cause.actions.map((action, index) => (

                <li key={action.id ?? index} className="text-sm leading-6">
                  {action.action_text || '—'}
                  {action.source_record_ids.length > 0 && (
                    <span className="text-xs text-muted-foreground font-mono">
                      {' '}
                      ({action.source_record_ids.join(', ')})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
        {cause.evidence.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-sm font-medium">
              {t('troubleshootingGuide.evidenceTitle')}
            </summary>
            <ul className="mt-2 flex flex-col gap-1.5">
              {cause.evidence.map((item, index) => (

                <li key={item.id ?? index} className="text-xs text-muted-foreground leading-5">
                  <span className="font-mono">
                    {t('troubleshootingGuide.recordRef', { id: item.record_id ?? '—' })}
                  </span>
                  {item.symptom_text && <span> — {item.symptom_text}</span>}
                  {item.repair_description && <span> — {item.repair_description}</span>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
  )

  /**
   * Source-report selector (M11C-6R2 Part D): the uploaded repair
   * report(s) backing the current knowledge database. Options carry the
   * stable record ID as the value and enough human context (filename,
   * rows, upload time, short ID) to tell duplicate filenames apart.
   * Deleted backing sources render a warning and are never remapped to
   * another same-named file.
   */
  const renderSourceSelector = () => {
    if (!sourceReports || sourceReports.length === 0) {
      return (
        <EmptyState
          icon={LifeBuoy}
          title={t('troubleshootingGuide.noSourcesTitle')}
          description={t('troubleshootingGuide.noSourcesDescription')}
        />
      )
    }
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t('troubleshootingGuide.selectSourceTitle')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Label htmlFor="troubleshooting-source">{t('troubleshootingGuide.sourceLabel')}</Label>
          <Select
            value={selectedSourceId}
            onValueChange={(id) => {
              setSelectedSourceId(id)
              setSelectedCode('')
              setSelectedModeId('')
            }}
          >
            <SelectTrigger id="troubleshooting-source" className="w-full">
              <SelectValue placeholder={t('troubleshootingGuide.sourcePlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              {sourceReports.map((report) => (
                <SelectItem key={report.id} value={report.id}>
                  {report.filename} · {report.data_rows ?? '—'} · {report.created ?? ''} · {report.id.slice(-6)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {backingReports.length > 0 && (
            <p className="text-xs text-muted-foreground">
              {t('troubleshootingGuide.sourceBacksDb', {
                filename: backingReports.map((report) => report.filename).join(', '),
              })}
            </p>
          )}
          {deletedBackingIds.length > 0 && (
            <Alert>
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{t('troubleshootingGuide.sourceDeletedWarning')}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>
    )
  }

  /**
   * Knowledge-source selector (M12): Text Mining vs LLM. Segmented
   * buttons (not another combobox) so the mining flow's selectors keep
   * their order. The choice determines which store supplies the guide —
   * results are never merged.
   */
  const renderKnowledgeSourceSelector = () => (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t('troubleshootingGuide.knowledgeSourceLabel')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex flex-wrap gap-2" role="group" aria-label={t('troubleshootingGuide.knowledgeSourceLabel')}>
          <Button
            variant={knowledgeSource === 'mining' ? 'default' : 'outline'}
            size="sm"
            aria-pressed={knowledgeSource === 'mining'}
            onClick={() => handleSelectKnowledgeSource('mining')}
          >
            {t('troubleshootingGuide.knowledgeSourceMining')}
          </Button>
          <Button
            variant={knowledgeSource === 'llm' ? 'default' : 'outline'}
            size="sm"
            aria-pressed={knowledgeSource === 'llm'}
            onClick={() => handleSelectKnowledgeSource('llm')}
          >
            {t('troubleshootingGuide.knowledgeSourceLLM')}
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          {t('troubleshootingGuide.knowledgeSourceDescription')}
        </p>
      </CardContent>
    </Card>
  )

  const LLM_RECORD_FIELDS = useMemo(
    () =>
      [
        { key: 'findings', titleKey: 'troubleshootingGuide.llmFindingsTitle' },
        { key: 'candidate_causes', titleKey: 'troubleshootingGuide.llmCausesTitle' },
        { key: 'diagnostic_steps', titleKey: 'troubleshootingGuide.llmDiagnosticsTitle' },
        { key: 'corrective_actions', titleKey: 'troubleshootingGuide.llmActionsTitle' },
        { key: 'verification_steps', titleKey: 'troubleshootingGuide.llmVerificationsTitle' },
        { key: 'post_repair_events', titleKey: 'troubleshootingGuide.llmEventsTitle' },
      ] as const,
    [],
  )

  const renderLlmRecord = (record: LLMGuide['records'][number], index: number) => {
    type LlmItem = { text: string | null; basis: string | null; source_quote: string | null }
    const supported = (items: LlmItem[]) =>
      items.filter((item) => item.basis === 'DATA_SUPPORTED')
    const inferred = (items: LlmItem[]) =>
      items.filter((item) => item.basis !== 'DATA_SUPPORTED')
    return (
      <Card key={record.id ?? record.source_record_id ?? index}>
        <CardHeader>
          <CardTitle className="text-sm font-medium font-mono">
            {t('troubleshootingGuide.recordRef', { id: record.source_record_id ?? '—' })}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {record.record_error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription className="font-mono text-xs break-words">
                {t('troubleshootingGuide.llmRecordErrorLabel')}: {record.record_error}
              </AlertDescription>
            </Alert>
          )}
          {record.symptom && (
            <div>
              <h4 className="text-sm font-medium">{t('troubleshootingGuide.llmSymptomTitle')}</h4>
              <p className="text-sm leading-6">{record.symptom}</p>
            </div>
          )}
          {record.source_text && (
            <details className="text-sm">
              <summary className="cursor-pointer text-sm font-medium">
                {t('troubleshootingGuide.llmSourceTextTitle')}
              </summary>
              <p className="mt-2 text-xs text-muted-foreground leading-5 whitespace-pre-wrap">
                {record.source_text}
              </p>
            </details>
          )}
          {LLM_RECORD_FIELDS.map(({ key, titleKey }) => {
            const items = (record[key] ?? []) as { text: string | null; basis: string | null; source_quote: string | null }[]
            if (items.length === 0) return null
            const historical = supported(items)
            const derived = inferred(items)
            return (
              <div key={key} className="space-y-2">
                <h4 className="text-sm font-medium">{t(titleKey)}</h4>
                {historical.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-muted-foreground">
                      {t('troubleshootingGuide.llmHistoricalTitle')}
                    </p>
                    <ul className="flex flex-col gap-1.5">
                      {historical.map((item, itemIndex) => (
                        <li key={itemIndex} className="text-sm leading-6">
                          {item.text || '—'}
                          <Badge variant="secondary" className="ms-2 font-mono text-[10px]">
                            {t('troubleshootingGuide.llmSupportedBadge')}
                          </Badge>
                          {item.source_quote && (
                            <span className="block text-xs text-muted-foreground">
                              {item.source_quote}
                            </span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {derived.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-xs font-medium text-muted-foreground">
                      {t('troubleshootingGuide.llmInferredTitle')}
                    </p>
                    <ul className="flex flex-col gap-1.5">
                      {derived.map((item, itemIndex) => (
                        <li key={itemIndex} className="text-sm leading-6">
                          {item.text || '—'}
                          <Badge variant="outline" className="ms-2 font-mono text-[10px]">
                            {t('troubleshootingGuide.llmInferredBadge')}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )
          })}
        </CardContent>
      </Card>
    )
  }

  /**
   * LLM guide branch (M12 §13–§18): build selector, source-report
   * selector (manifest-backed, stable IDs, deleted-safe), then the
   * provenance-headed guide. Never queries the mining store.
   */
  const renderLlmBranch = () => {
    if (!llmBuilds || llmBuilds.length === 0) {
      return (
        <EmptyState
          icon={LifeBuoy}
          title={t('troubleshootingGuide.noLLMBuildsTitle')}
          description={t('troubleshootingGuide.noLLMBuildsDescription')}
        />
      )
    }
    return (
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('troubleshootingGuide.llmBuildLabel')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Label htmlFor="llm-build">{t('troubleshootingGuide.llmBuildLabel')}</Label>
            <Select
              value={effectiveBuild?.id ?? ''}
              onValueChange={(id) => {
                setSelectedBuildId(id)
                setSelectedLlmSourceId('')
              }}
            >
              <SelectTrigger id="llm-build" className="w-full">
                <SelectValue placeholder={t('troubleshootingGuide.llmBuildPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {[...(llmBuilds ?? [])]
                  .sort((a, b) => (b.created ?? '').localeCompare(a.created ?? ''))
                  .map((build) => (
                    <SelectItem key={build.id} value={build.id}>
                      {build.id.slice(-6)} · {build.status} · {build.record_count ?? '—'} · {build.created ?? ''} · {build.id.slice(-6)}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </CardContent>
        </Card>

        {effectiveBuild && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('troubleshootingGuide.selectSourceTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <Label htmlFor="llm-source">{t('troubleshootingGuide.sourceLabel')}</Label>
              <Select value={selectedLlmSourceId} onValueChange={setSelectedLlmSourceId}>
                <SelectTrigger id="llm-source" className="w-full">
                  <SelectValue placeholder={t('troubleshootingGuide.sourcePlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {llmManifestSources.map((entry) => {
                    const deleted = llmSourceDeleted(entry.report_id)
                    const label = `${entry.filename ?? entry.report_id} · ${entry.report_id.slice(-6)}${deleted ? ' · ✕' : ''}`
                    return (
                      <SelectItem key={entry.report_id} value={entry.report_id}>
                        {label}
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
            </CardContent>
          </Card>
        )}

        {effectiveBuild && selectedLlmSourceId && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('troubleshootingGuide.guideTitle')}</CardTitle>
            </CardHeader>
            <CardContent>{renderLlmGuide()}</CardContent>
          </Card>
        )}
      </div>
    )
  }

  const renderLlmGuide = () => {
    if (llmGuideLoading) {
      return (
        <div className="flex items-center justify-center py-8">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (llmGuideError || !llmGuide) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('troubleshootingGuide.llmGuideLoadFailed')}</span>
            <Button variant="outline" size="sm" onClick={() => refetchLlmGuide()} className="shrink-0">
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }
    if (llmGuide.source_deleted) {
      return (
        <EmptyState
          icon={LifeBuoy}
          title={t('troubleshootingGuide.llmSourceDeletedTitle')}
          description={t('troubleshootingGuide.llmSourceDeletedDescription')}
        />
      )
    }
    if (llmGuide.warnings.includes('no_records_for_source') || llmGuide.records.length === 0) {
      return (
        <EmptyState
          icon={LifeBuoy}
          title={t('troubleshootingGuide.llmNoRecordsTitle')}
          description={t('troubleshootingGuide.llmNoRecordsDescription')}
        />
      )
    }
    return (
      <div className="space-y-4" data-testid="llm-guide">
        <Card>
          <CardContent className="pt-4">
            <div className="flex flex-wrap gap-2">
              <Badge variant="default" className="font-mono text-[11px]">
                {t('troubleshootingGuide.knowledgeSourceLLM')}
              </Badge>
              <Badge variant="secondary" className="font-mono text-[11px]">
                {t('troubleshootingGuide.llmBuildLabelShort')}: {llmGuide.build_id.slice(-6)}
              </Badge>
              {llmGuide.model && (
                <Badge variant="secondary" className="font-mono text-[11px]">
                  {t('troubleshootingGuide.llmModelLabel')}: {llmGuide.model}
                </Badge>
              )}
              {llmGuide.prompt_version && (
                <Badge variant="outline" className="font-mono text-[11px]">
                  {llmGuide.prompt_version}
                </Badge>
              )}
            </div>
            <p className="mt-2 text-xs text-muted-foreground font-mono break-words">
              {llmGuide.source_filename ?? llmGuide.source_report_id} · {llmGuide.source_report_id}
            </p>
          </CardContent>
        </Card>
        {llmGuide.records.map(renderLlmRecord)}
      </div>
    )
  }

  const renderGuide = () => {
    if (!selectedModeId) return null
    if (guideLoading) {
      return (
        <div className="flex items-center justify-center py-8">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (guideError || !guide) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('troubleshootingGuide.guideLoadFailed')}</span>
            <Button variant="outline" size="sm" onClick={() => refetchGuide()} className="shrink-0">
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }
    if (guide.causes.length === 0) {
      return (
        <EmptyState
          icon={LifeBuoy}
          title={t('troubleshootingGuide.noGuideTitle')}
          description={t('troubleshootingGuide.noGuideDescription')}
        />
      )
    }
    return (
      <div className="space-y-4">
        {guide.warnings.includes(INSUFFICIENT_EVIDENCE_WARNING) && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>{INSUFFICIENT_EVIDENCE_WARNING}</AlertTitle>
            <AlertDescription>{t('troubleshootingGuide.insufficientEvidence')}</AlertDescription>
          </Alert>
        )}
        <p className="text-sm text-muted-foreground">
          {t('troubleshootingGuide.equipmentLabel')}:{' '}
          <span className="font-mono font-medium text-foreground">{guide.equipment_code}</span>
          {' · '}
          {t('troubleshootingGuide.failureModeLabel')}:{' '}
          <span className="font-medium text-foreground">{guide.failure_mode_label}</span>
        </p>
        {guide.symptom_summary && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">
                {t('troubleshootingGuide.symptomSummary')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-7 whitespace-pre-wrap">{guide.symptom_summary}</p>
            </CardContent>
          </Card>
        )}
        <h3 className="text-sm font-medium">{t('troubleshootingGuide.causesTitle')}</h3>
        {guide.causes.map(renderCause)}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">
              {t('troubleshootingGuide.recommendedActionsTitle')}
            </CardTitle>
          </CardHeader>
          <CardContent data-testid="recommended-actions">
            {recommendedActions.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t('troubleshootingGuide.noRecommendedActions')}
              </p>
            ) : (
              <ol className="flex flex-col gap-2 list-decimal ms-5">
                {recommendedActions.map((action) => (
                  <li
                    key={action.id ?? action.action_text}
                    className="text-sm leading-6"
                  >
                    {action.guide_instruction ?? action.action_text ?? '—'}
                    {action.guide_instruction && action.action_text && (
                      <span className="block text-xs text-muted-foreground">
                        {t('troubleshootingGuide.basedOnLabel', { text: action.action_text })}
                      </span>
                    )}
                    <span className="flex flex-wrap gap-1.5 mt-1">
                      {action.role && (
                        <Badge variant="secondary" className="font-mono text-[11px]">
                          {action.role}
                        </Badge>
                      )}
                      {typeof action.frequency === 'number' && (
                        <Badge variant="outline" className="font-mono text-[11px]">
                          ×{action.frequency}
                        </Badge>
                      )}
                    </span>
                    {action.source_record_ids.length > 0 && (
                      <span className="block text-xs text-muted-foreground font-mono">
                        {action.source_record_ids.join(', ')}
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
        {methodSection?.body && (
          <p className="text-xs text-muted-foreground leading-5">
            {methodSection.title ? `${methodSection.title}: ` : ''}
            {methodSection.body}
          </p>
        )}
        {guide.safety_notes.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">
                {t('troubleshootingGuide.safetyTitle')}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-1.5">
                {guide.safety_notes.map((note, index) => (

                  <li key={index} className="text-sm leading-6">
                    {note.note_text || '—'}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </div>
    )
  }

  const renderBody = () => {
    if (statusLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (statusError || !status) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('troubleshootingGuide.equipmentLoadFailed')}</span>
            <Button variant="outline" size="sm" onClick={() => refetchStatus()} className="shrink-0">
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }
    if (!available) {
      const incompatible = status.state === 'incompatible'
      return (
        <EmptyState
          icon={LifeBuoy}
          title={t('troubleshootingGuide.databaseUnavailableTitle')}
          description={t(
            incompatible
              ? 'troubleshootingGuide.databaseIncompatibleDesc'
              : 'troubleshootingGuide.databaseUnavailableDesc',
          )}
        />
      )
    }
    if (equipmentLoading && knowledgeSource === 'mining') {
      return (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (equipmentError && knowledgeSource === 'mining') {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('troubleshootingGuide.equipmentLoadFailed')}</span>
            <Button variant="outline" size="sm" onClick={() => refetchEquipment()} className="shrink-0">
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }
    if ((!equipment || equipment.length === 0) && knowledgeSource === 'mining') {
      return (
        <EmptyState
          icon={LifeBuoy}
          title={t('troubleshootingGuide.noEquipmentTitle')}
          description={t('troubleshootingGuide.noEquipmentDescription')}
        />
      )
    }

    return (
      <div className="space-y-6">
        {renderKnowledgeSourceSelector()}
        {knowledgeSource === 'llm' ? (
          renderLlmBranch()
        ) : (
        <>
        {renderSourceSelector()}
        {sourceMismatch ? (
          <EmptyState
            icon={LifeBuoy}
            title={t('troubleshootingGuide.sourceMismatchTitle')}
            description={t('troubleshootingGuide.sourceMismatchDescription')}
          />
        ) : (
          <>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('troubleshootingGuide.selectEquipmentTitle')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Label htmlFor="troubleshooting-equipment">{t('troubleshootingGuide.equipmentLabel')}</Label>
            <Select value={selectedCode} onValueChange={handleSelectCode}>
              <SelectTrigger id="troubleshooting-equipment" className="w-full">
                <SelectValue placeholder={t('troubleshootingGuide.equipmentPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                {(equipment ?? []).map((item) => (
                  <SelectItem key={item.code} value={item.code}>
                    {item.code}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </CardContent>
        </Card>

        {selectedCode && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('troubleshootingGuide.selectFailureModeTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {modesLoading ? (
                <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
                  <LoadingSpinner size="sm" />
                </div>
              ) : modesError || !failureModes ? (
                <Button variant="link" size="sm" onClick={() => refetchModes()}>
                  {t('troubleshootingGuide.failureModesLoadFailed')}
                </Button>
              ) : failureModes.length === 0 ? (
                <EmptyState
                  icon={LifeBuoy}
                  title={t('troubleshootingGuide.noFailureModesTitle')}
                  description={t('troubleshootingGuide.noFailureModesDescription', { code: selectedCode })}
                />
              ) : (
                <div className="space-y-2">
                  <Label htmlFor="troubleshooting-mode">{t('troubleshootingGuide.failureModeLabel')}</Label>
                  <Select value={selectedModeId} onValueChange={setSelectedModeId}>
                    <SelectTrigger id="troubleshooting-mode" className="w-full">
                      <SelectValue placeholder={t('troubleshootingGuide.failureModePlaceholder')} />
                    </SelectTrigger>
                    <SelectContent>
                      {failureModes.map((mode) => (
                        <SelectItem key={mode.id} value={mode.id}>
                          {mode.label} ({mode.record_count})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {selectedCode && selectedModeId && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('troubleshootingGuide.guideTitle')}</CardTitle>
            </CardHeader>
            <CardContent>{renderGuide()}</CardContent>
          </Card>
        )}
          </>
        )}
        </>
        )}
      </div>
    )
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-[var(--custom-page)] text-[var(--custom-foreground)]">
        <div className="p-6 space-y-6">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">{t('troubleshootingGuide.title')}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t('troubleshootingGuide.description')}</p>
          </div>
          {renderBody()}
        </div>
      </div>
    </AppShell>
  )
}
