'use client'

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertCircle, FileSpreadsheet, Pencil, Plus, RefreshCw, Trash2, Wrench } from 'lucide-react'
import {
  useCreateFailureMode,
  useDeleteFailureMode,
  useFailureModes,
  useUpdateFailureMode,
} from '@/lib/hooks/use-failure-modes'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { CreateFailureModeRequest, FailureModeResponse } from '@/lib/types/api'
import { FailureModeDialog } from './FailureModeDialog'
import { FailureModeImportDialog } from './FailureModeImportDialog'

/**
 * Failure-mode database section (دیتابیس حالت خرابی تجهیزات).
 * Owns failure-mode composition (list, create/edit dialog, delete
 * confirmation, Excel import) while reusing the same UI primitives as
 * the equipment section. All persistence goes through the dedicated
 * `/api/failure-modes` endpoints (the `failure_mode` table only) —
 * never through the equipment `asset` endpoints.
 */
export function FailureModesSection() {
  const { t } = useTranslation()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [editing, setEditing] = useState<FailureModeResponse | null>(null)
  const [deleting, setDeleting] = useState<FailureModeResponse | null>(null)
  const { data: modes, isLoading, isError, refetch } = useFailureModes()
  const createMode = useCreateFailureMode()
  const updateMode = useUpdateFailureMode()
  const deleteMode = useDeleteFailureMode()

  const openCreate = () => {
    setEditing(null)
    setDialogOpen(true)
  }

  const openEdit = (mode: FailureModeResponse) => {
    setEditing(mode)
    setDialogOpen(true)
  }

  const handleSubmit = async (data: CreateFailureModeRequest) => {
    if (editing) {
      await updateMode.mutateAsync({ id: editing.id, data })
    } else {
      await createMode.mutateAsync(data)
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleting) return
    await deleteMode.mutateAsync(deleting.id)
    setDeleting(null)
  }

  const renderContent = () => {
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
            <span>{t('failureModes.loadFailed')}</span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetch()}
              className="shrink-0"
            >
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.refresh')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }

    if (!modes || modes.length === 0) {
      return (
        <EmptyState
          icon={Wrench}
          title={t('failureModes.emptyTitle')}
          description={t('failureModes.emptyDescription')}
          action={
            <div className="mt-4 flex flex-col sm:flex-row gap-2">
              <Button onClick={() => setImportOpen(true)} variant="outline">
                <FileSpreadsheet className="h-4 w-4 me-2" />
                {t('failureModes.importButton')}
              </Button>
              <Button onClick={openCreate} variant="outline">
                <Plus className="h-4 w-4 me-2" />
                {t('failureModes.newMode')}
              </Button>
            </div>
          }
        />
      )
    }

    return (
      <div className="rounded-md border border-[var(--custom-border)] bg-[var(--custom-surface)] overflow-auto">
        <table className="w-full min-w-[720px] outline-none table-fixed">
          <thead className="sticky top-0 bg-background z-10">
            <tr className="border-b">
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground w-[130px]">
                {t('failureModes.code')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('failureModes.label')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground w-[120px]">
                {t('failureModes.status')}
              </th>
              <th className="h-12 px-4 text-end align-middle font-medium text-muted-foreground w-[130px]">
                {t('common.actions')}
              </th>
            </tr>
          </thead>
          <tbody>
            {modes.map((mode) => (
              <tr
                key={mode.id}
                className="border-b transition-colors hover:bg-[var(--surface-raised)]"
              >
                <td className="h-12 px-4">
                  <span className="font-mono text-sm font-medium">{mode.code}</span>
                </td>
                <td className="h-12 px-4">
                  <div className="flex flex-col overflow-hidden">
                    <span className="font-medium truncate">{mode.label}</span>
                    {mode.description && (
                      <span className="text-xs text-muted-foreground truncate">
                        {mode.description}
                      </span>
                    )}
                  </div>
                </td>
                <td className="h-12 px-4">
                  <Badge variant="secondary" className="font-mono text-[11px]">
                    {mode.status}
                  </Badge>
                </td>
                <td className="h-12 px-4 text-end">
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => openEdit(mode)}
                      aria-label={t('failureModes.editMode')}
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setDeleting(mode)}
                      aria-label={t('failureModes.deleteTitle')}
                      className="text-destructive hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-xl font-bold tracking-tight">{t('failureModes.title')}</h2>
          <p className="mt-1 text-sm text-muted-foreground">{t('failureModes.description')}</p>
        </div>
        {modes && modes.length > 0 && (
          <div className="flex gap-2">
            <Button onClick={() => setImportOpen(true)} variant="outline">
              <FileSpreadsheet className="h-4 w-4 me-2" />
              {t('failureModes.importButton')}
            </Button>
            <Button onClick={openCreate}>
              <Plus className="h-4 w-4 me-2" />
              {t('failureModes.newMode')}
            </Button>
          </div>
        )}
      </div>

      {renderContent()}

      <FailureModeDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode={editing}
        onSubmit={handleSubmit}
        isPending={createMode.isPending || updateMode.isPending}
      />

      <FailureModeImportDialog open={importOpen} onOpenChange={setImportOpen} />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
        title={t('failureModes.deleteTitle')}
        description={t('failureModes.deleteConfirm', { name: deleting?.label ?? '' })}
        confirmText={t('common.delete')}
        confirmVariant="destructive"
        onConfirm={handleDeleteConfirm}
      />
    </div>
  )
}
