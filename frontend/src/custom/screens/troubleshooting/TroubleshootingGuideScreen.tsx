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
  const [selectedCode, setSelectedCode] = useState<string>('')
  const [selectedModeId, setSelectedModeId] = useState<string>('')
  const [selectedSourceId, setSelectedSourceId] = useState<string>('')

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

  const handleSelectCode = (code: string) => {
    setSelectedCode(code)
    setSelectedModeId('')
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
    if (equipmentLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (equipmentError) {
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
    if (!equipment || equipment.length === 0) {
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
                {equipment.map((item) => (
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
