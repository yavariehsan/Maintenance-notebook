'use client'

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
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
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { AlertCircle, FileSpreadsheet, RefreshCw, Trash2, Upload } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { getDateLocale } from '@/lib/utils/date-locale'
import {
  useDeleteRepairReport,
  useRepairReports,
  useUploadRepairReport,
} from '@/lib/hooks/use-repair-reports'
import { useToast } from '@/lib/hooks/use-toast'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { RepairReport } from '@/lib/api/repair-reports'

/**
 * Downstream repair-reports collection screen (گردآوری → گزارشات تعمیر).
 * Lists uploaded repair-history workbooks with their analysis states,
 * uploads new ones, and deletes reports by stable record ID (never by
 * filename alone) through an explicit confirm dialog. Reuses upstream
 * AppShell, table, Badge, EmptyState and Alert primitives — no second
 * list architecture.
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

export function RepairReportsScreen() {
  const { t, language } = useTranslation()
  const { toast } = useToast()
  const router = useRouter()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { data: reports, isLoading, isError, refetch } = useRepairReports()
  const uploadMutation = useUploadRepairReport()
  const deleteMutation = useDeleteRepairReport()
  const [pendingDelete, setPendingDelete] = useState<RepairReport | null>(null)

  const handlePickFile = () => fileInputRef.current?.click()

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    if (!/\.xlsx?m?$/i.test(file.name)) {
      // Client-side guard with feedback; the API re-validates regardless.
      toast({
        title: t('common.error'),
        description: t('repairReports.invalidFileType'),
        variant: 'destructive',
      })
      return
    }
    uploadMutation.mutate(file)
  }

  const renderBody = () => {
    if (isLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (isError) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('repairReports.loadFailed')}</span>
            <Button variant="outline" size="sm" onClick={() => refetch()} className="shrink-0">
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }
    if (!reports || reports.length === 0) {
      return (
        <EmptyState
          icon={FileSpreadsheet}
          title={t('repairReports.emptyTitle')}
          description={t('repairReports.emptyDescription')}
          action={
            <div className="mt-4">
              <Button
                onClick={handlePickFile}
                disabled={uploadMutation.isPending}
                title={t('repairReports.uploadDescription')}
              >
                <Upload className="h-4 w-4 me-2" />
                {t('repairReports.uploadButton')}
              </Button>
            </div>
          }
        />
      )
    }
    return (
      <div className="rounded-md border border-[var(--custom-border)] bg-[var(--custom-surface)] overflow-auto">
        <table className="w-full min-w-[800px] outline-none table-fixed">
          <thead className="sticky top-0 bg-background z-10">
            <tr className="border-b">
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('repairReports.fileColumn')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground w-[110px]">
                {t('repairReports.rowsColumn')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground w-[170px]">
                {t('repairReports.statusColumn')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground w-[150px] hidden sm:table-cell">
                {t('repairReports.updatedColumn')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground w-[90px]">
                <span className="sr-only">{t('repairReports.deleteReport')}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {reports.map((report) => {
              const deletable =
                report.analysis_state !== 'queued' && report.analysis_state !== 'processing'
              return (
              <tr
                key={report.id}
                className="border-b transition-colors hover:bg-[var(--surface-raised)] cursor-pointer"
                onClick={() => router.push(`/repair-reports/${encodeURIComponent(report.id)}`)}
              >
                <td className="h-12 px-4">
                  <div className="flex flex-col overflow-hidden">
                    <span className="font-medium truncate">{report.filename}</span>
                    <span className="text-xs text-muted-foreground truncate">
                      {report.sheet ?? ''}
                    </span>
                  </div>
                </td>
                <td className="h-12 px-4 text-sm text-muted-foreground font-mono">
                  {report.data_rows ?? '—'}
                </td>
                <td className="h-12 px-4">
                  <Badge variant="secondary" className="font-mono text-[11px]">
                    {t(statusLabelKey(report.analysis_state))}
                  </Badge>
                </td>
                <td className="h-12 px-4 text-muted-foreground text-sm hidden sm:table-cell whitespace-nowrap">
                  {report.updated
                    ? formatDistanceToNow(new Date(report.updated), {
                        addSuffix: true,
                        locale: getDateLocale(language),
                      })
                    : '—'}
                </td>
                <td className="h-12 px-4">
                  {deletable ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={t('repairReports.deleteReport')}
                      disabled={deleteMutation.isPending}
                      onClick={(event) => {
                        event.stopPropagation()
                        setPendingDelete(report)
                      }}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  ) : (
                    <span className="text-sm text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-[var(--custom-page)] text-[var(--custom-foreground)]">
        <div className="p-6 space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="font-display text-2xl font-bold tracking-tight">{t('repairReports.title')}</h1>
              <p className="mt-1 text-sm text-muted-foreground">{t('repairReports.description')}</p>
            </div>
            <Button
              onClick={handlePickFile}
              disabled={uploadMutation.isPending}
              title={t('repairReports.uploadDescription')}
            >
              {uploadMutation.isPending ? (
                <LoadingSpinner size="sm" className="me-2" />
              ) : (
                <Upload className="h-4 w-4 me-2" />
              )}
              {t('repairReports.uploadButton')}
            </Button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xlsm"
            className="hidden"
            onChange={handleFileChange}
            aria-label={t('repairReports.uploadTitle')}
          />
          {renderBody()}
        </div>
      </div>
      <AlertDialog open={pendingDelete !== null} onOpenChange={(open) => { if (!open) setPendingDelete(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('repairReports.deleteReportTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('repairReports.deleteReportDescription')}
              {pendingDelete && (
                <span className="mt-2 block font-mono text-xs">
                  {pendingDelete.filename}
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
                if (pendingDelete) {
                  deleteMutation.mutate(pendingDelete.id, {
                    onSuccess: () => setPendingDelete(null),
                  })
                }
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
