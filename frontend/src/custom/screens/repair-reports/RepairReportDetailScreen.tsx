'use client'

import { useRouter } from 'next/navigation'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { AlertCircle, ArrowLeft, FileSpreadsheet, RefreshCw } from 'lucide-react'
import {
  useRepairReport,
  useRepairReportPreview,
  useStartRepairAnalysis,
} from '@/lib/hooks/use-repair-reports'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { RepairReport } from '@/lib/api/repair-reports'

/**
 * Downstream repair-report detail: exactly two tabs — محتوا (10-row
 * preview of the uploaded workbook, never the engine) and تحلیل (the
 * تحلیل محتوا control surface). Reuses the sources-detail tab/table
 * conventions with no extra sections.
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
  const analyzeMutation = useStartRepairAnalysis()

  const report = detail?.report ?? null
  const canAnalyze =
    report?.analysis_state === 'not_analyzed' || report?.analysis_state === 'failed'

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
    </AppShell>
  )
}
