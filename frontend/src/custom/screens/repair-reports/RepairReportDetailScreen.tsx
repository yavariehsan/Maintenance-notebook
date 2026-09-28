'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { useQueryClient } from '@tanstack/react-query'
import { QUERY_KEYS } from '@/lib/api/query-client'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { AlertCircle, ArrowLeft, FileSpreadsheet, RefreshCw, Trash2 } from 'lucide-react'
import {
  useDeleteRepairReport,
  useRepairReport,
  useRepairReportActions,
  useRepairReportPreview,
  useStartSingleReportAnalysis,
} from '@/lib/hooks/use-repair-reports'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { RepairReport } from '@/lib/api/repair-reports'

/**
 * Downstream repair-report detail: exactly two tabs — محتوا (10-row
 * preview of the uploaded workbook, never the engine) and تحلیل (the
 * per-report تحلیل محتوا control surface plus the report-scoped repair
 * actions mined from this file alone). Reuses the sources-detail tab/table
 * conventions and the troubleshooting guide's action rendering primitives
 * (badges, role/frequency, record refs) with no new scoring.
 */
function statusLabelKey(state: RepairReport['analysis_state']): string {
  switch (state) {
    case 'queued':
      return 'repairReports.statusQueued'
    case 'processing':
      return 'repairReports.statusProcessing'
    case 'completed':
      return 'repairReports.statusCompleted'
    case 'failed':
      return 'repairReports.statusFailed'
    case 'not_analyzed':
    default:
      return 'repairReports.statusNotAnalyzed'
  }
}

function statusDescKey(state: RepairReport['analysis_state']): string {
  switch (state) {
    case 'queued':
      return 'repairReports.statusQueuedDesc'
    case 'processing':
      return 'repairReports.statusProcessingDesc'
    case 'completed':
      return 'repairReports.statusCompletedDesc'
    case 'failed':
      return 'repairReports.statusFailedDesc'
    case 'not_analyzed':
    default:
      return 'repairReports.statusNotAnalyzedDesc'
  }
}

function formatCell(value: string | number | boolean | null): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? '✓' : '✗'
  return String(value)
}

export function RepairReportDetailScreen({ reportId }: { reportId: string }) {
  const { t } = useTranslation()
  const router = useRouter()
  const queryClient = useQueryClient()
  const {
    data: detail,
    isLoading,
    isError,
    refetch,
  } = useRepairReport(reportId)
  const {
    data: preview,
    isLoading: previewLoading,
    isError: previewError,
    refetch: refetchPreview,
  } = useRepairReportPreview(reportId)
  const analyzeMutation = useStartSingleReportAnalysis(reportId)
  const deleteMutation = useDeleteRepairReport()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const {
    data: actions,
    isLoading: actionsLoading,
    isError: actionsError,
    refetch: refetchActions,
  } = useRepairReportActions(reportId)

  const report = detail?.report ?? null
  const analysisState = report?.analysis_state ?? null
  const canAnalyze =
    analysisState === 'not_analyzed' || analysisState === 'failed'

  // When polling observes the run reaching a terminal state, refresh the
  // dependent caches once: the troubleshooting guide data (a new database
  // may have landed), the report-scoped actions, and the reports list.
  // Transient states keep polling quietly without extra invalidation traffic.
  const previousState = useRef<string | null>(null)
  useEffect(() => {
    const wasActive =
      previousState.current === 'queued' || previousState.current === 'processing'
    const isTerminal = analysisState === 'completed' || analysisState === 'failed'
    if (wasActive && isTerminal) {
      queryClient.invalidateQueries({ queryKey: ['troubleshooting'] })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.repairReports })
      queryClient.invalidateQueries({ queryKey: QUERY_KEYS.repairReportActions(reportId) })
    }
    previousState.current = analysisState
  }, [analysisState, queryClient, reportId])

  const renderPreview = () => {
    if (previewLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (previewError || !preview) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('repairReports.previewFailed')}</span>
            <Button variant="outline" size="sm" onClick={() => refetchPreview()} className="shrink-0">
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }
    if (preview.rows.length === 0) {
      return (
        <EmptyState
          icon={FileSpreadsheet}
          title={t('repairReports.noPreviewRows')}
          description={t('repairReports.previewNote', { shown: 0, total: preview.total_data_rows })}
        />
      )
    }
    return (
      <div className="space-y-3">
        <p className="text-xs text-muted-foreground">
          {t('repairReports.previewNote', {
            shown: preview.rows.length,
            total: preview.total_data_rows,
          })}
        </p>
        <div className="rounded-md border border-[var(--custom-border)] bg-[var(--custom-surface)] overflow-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="sticky top-0 bg-background z-10">
              <tr className="border-b">
                {preview.columns.map((column, index) => (
                  <th

                    key={index}
                    className="h-10 px-3 text-start align-middle font-medium text-muted-foreground whitespace-nowrap max-w-[240px] truncate"
                    title={column || undefined}
                  >
                    {column || '—'}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, rowIndex) => (

                <tr key={rowIndex} className="border-b last:border-0 hover:bg-[var(--surface-raised)]">
                  {row.map((cell, cellIndex) => (
                    <td

                      key={cellIndex}
                      className="px-3 py-2 align-top max-w-[240px] truncate"
                      title={formatCell(cell) || undefined}
                    >
                      {formatCell(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  const renderActions = () => {
    if (actionsLoading) {
      return (
        <div className="flex items-center justify-center py-8">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (actionsError || !actions) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('repairReports.actionsLoadFailed')}</span>
            <Button variant="outline" size="sm" onClick={() => refetchActions()} className="shrink-0">
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }
    const hasObjects =
      actions.repair_actions.length > 0 ||
      actions.verifications.length > 0 ||
      actions.post_repair_events.length > 0 ||
      actions.history_only_record_ids.length > 0
    if (!hasObjects) {
      return (
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm font-medium">{t('repairReports.noActionsTitle')}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {actions.warnings.includes('report_not_in_latest_db')
                ? t('repairReports.notInLatestDb')
                : t('repairReports.noActionsDescription')}
            </p>
          </CardContent>
        </Card>
      )
    }
    return (
      <div className="space-y-4">
        {actions.warnings.includes('report_not_in_latest_db') && (
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{t('repairReports.notInLatestDb')}</AlertDescription>
          </Alert>
        )}
        {actions.repair_actions.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">
                {t('repairReports.actionsTitle')} ({actions.repair_actions.length})
              </CardTitle>
            </CardHeader>
            <CardContent data-testid="report-actions">
              <ol className="flex flex-col gap-2 list-decimal ms-5">
                {actions.repair_actions.map((action) => (
                  <li
                    key={action.id ?? action.action_text}
                    className="text-sm leading-6"
                  >
                    {action.guide_instruction || action.action_text || '—'}
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
                      {action.category && (
                        <Badge variant="outline" className="font-mono text-[11px]">
                          {action.category}
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
            </CardContent>
          </Card>
        )}
        {actions.verifications.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">
                {t('repairReports.verificationsTitle')} ({actions.verifications.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-1.5">
                {actions.verifications.map((item, index) => (
                  <li key={item.id ?? index} className="text-sm leading-6">
                    {item.sentence || '—'}
                    <span className="flex flex-wrap gap-1.5 mt-1">
                      {item.event_type && (
                        <Badge variant="secondary" className="font-mono text-[11px]">
                          {item.event_type}
                        </Badge>
                      )}
                    </span>
                    {item.record_id && (
                      <span className="block text-xs text-muted-foreground font-mono">
                        {t('repairReports.recordRef', { id: item.record_id })}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
        {actions.post_repair_events.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">
                {t('repairReports.eventsTitle')} ({actions.post_repair_events.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-1.5">
                {actions.post_repair_events.map((item, index) => (
                  <li key={item.id ?? index} className="text-sm leading-6">
                    {item.sentence || '—'}
                    <span className="flex flex-wrap gap-1.5 mt-1">
                      {item.event_type && (
                        <Badge variant="secondary" className="font-mono text-[11px]">
                          {item.event_type}
                        </Badge>
                      )}
                    </span>
                    {item.record_id && (
                      <span className="block text-xs text-muted-foreground font-mono">
                        {t('repairReports.recordRef', { id: item.record_id })}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
        {actions.history_only_record_ids.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">
                {t('repairReports.historyOnlyTitle')} ({actions.history_only_record_ids.length})
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-muted-foreground font-mono break-words">
                {actions.history_only_record_ids.join(', ')}
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    )
  }

  const renderAnalysis = () => {
    if (!report) return null
    const active = report.analysis_state === 'queued' || report.analysis_state === 'processing'
    return (
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              {t('repairReports.analysisTab')}
              <Badge variant="secondary" className="font-mono text-[11px]">
                {t(statusLabelKey(report.analysis_state))}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">
              {t(statusDescKey(report.analysis_state))}
            </p>
            <p className="text-xs text-muted-foreground">
              {t('repairReports.singleReportHint')}
            </p>
            {report.analysis_state === 'failed' && report.last_error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>{t('repairReports.statusFailed')}</AlertTitle>
                <AlertDescription className="font-mono text-xs break-words">
                  {report.last_error}
                </AlertDescription>
              </Alert>
            )}
            {report.analysis_state === 'completed' && (
              <p className="text-sm text-muted-foreground">
                {t('repairReports.viewGuideHint')}
              </p>
            )}
            <Button
              onClick={() => analyzeMutation.mutate()}
              disabled={!canAnalyze || analyzeMutation.isPending}
            >
              {analyzeMutation.isPending || active ? (
                <LoadingSpinner size="sm" className="me-2" />
              ) : null}
              {t('repairReports.analyzeButton')}
            </Button>
            {detail?.last_run && (
              <p className="text-xs text-muted-foreground font-mono">
                {t('repairReports.runLabel')}: {detail.last_run.id}
                {' · '}
                {t('repairReports.runIncludes', { count: detail.last_run.report_ids.length })}
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('repairReports.actionsTitle')}</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-4 text-sm text-muted-foreground">
              {t('repairReports.actionsDescription')}
            </p>
            {renderActions()}
          </CardContent>
        </Card>
      </div>
    )
  }

  const renderBody = () => {
    if (isLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (isError || !report) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('repairReports.reportNotFound')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('repairReports.reportNotFoundDesc')}</span>
            <Button variant="outline" size="sm" onClick={() => refetch()} className="shrink-0">
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="font-display text-2xl font-bold tracking-tight truncate">
            {report.filename}
          </h1>
          <Badge variant="secondary" className="font-mono text-[11px]">
            {t(statusLabelKey(report.analysis_state))}
          </Badge>
          {(report.analysis_state !== 'queued' && report.analysis_state !== 'processing') && (
            <Button
              variant="ghost"
              size="sm"
              aria-label={t('repairReports.deleteReport')}
              disabled={deleteMutation.isPending}
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
        <Tabs defaultValue="content" className="w-full">
          <TabsList className="w-full sticky top-0 z-10 bg-card">
            <TabsTrigger value="content">{t('repairReports.contentTab')}</TabsTrigger>
            <TabsTrigger value="analysis">{t('repairReports.analysisTab')}</TabsTrigger>
          </TabsList>
          <TabsContent value="content" className="mt-5">
            {renderPreview()}
          </TabsContent>
          <TabsContent value="analysis" className="mt-5">
            {renderAnalysis()}
          </TabsContent>
        </Tabs>
      </div>
    )
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-[var(--custom-page)] text-[var(--custom-foreground)]">
        <div className="p-6 space-y-6">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => router.push('/repair-reports')}
          >
            <ArrowLeft className="me-2 h-4 w-4 rtl:rotate-180" />
            {t('repairReports.backToReports')}
          </Button>
          {renderBody()}
        </div>
      </div>
      <AlertDialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('repairReports.deleteReportTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('repairReports.deleteReportDescription')}
              {report && (
                <span className="mt-2 block font-mono text-xs">
                  {report.filename}
                </span>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteMutation.isPending}>
              {t('common.cancel')}
            </AlertDialogCancel>
            <AlertDialogAction
              disabled={deleteMutation.isPending}
              onClick={() => {
                deleteMutation.mutate(reportId, {
                  onSuccess: () => router.push('/repair-reports'),
                })
              }}
            >
              {t('repairReports.deleteReport')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </AppShell>
  )
}
