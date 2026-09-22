'use client'

import { useRef, useState } from 'react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertCircle, CheckCircle2, FileSpreadsheet } from 'lucide-react'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { useTranslation } from '@/lib/hooks/use-translation'
import { useImportEquipment } from '@/lib/hooks/use-maintenance'
import type { EquipmentImportPreview } from '@/lib/types/api'

interface AssetImportDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Downstream Excel equipment import. Two-step workflow against
 * POST /api/assets/import: select file -> dry-run preview (row counts,
 * valid rows, per-row issues) -> confirm persists valid rows only.
 * Duplicate codes are rejected, never overwritten.
 */
export function AssetImportDialog({ open, onOpenChange }: AssetImportDialogProps) {
  const { t } = useTranslation()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [fileName, setFileName] = useState<string | null>(null)
  const [preview, setPreview] = useState<EquipmentImportPreview | null>(null)
  const importEquipment = useImportEquipment()

  const reset = () => {
    setFileName(null)
    setPreview(null)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const closeDialog = () => {
    onOpenChange(false)
    // Let the close animation finish before clearing state.
    setTimeout(reset, 200)
  }

  const runImport = async (file: File, dryRun: boolean) => {
    const result = await importEquipment.mutateAsync({ file, dryRun })
    setPreview(result)
  }

  const handleFileSelect = async (file: File | undefined) => {
    if (!file) return
    setFileName(file.name)
    setPreview(null)
    await runImport(file, true)
  }

  const handleConfirm = async () => {
    const file = fileInputRef.current?.files?.[0]
    if (!file) return
    await runImport(file, false)
  }

  const confirmed = preview !== null && preview.imported_count > 0
  const hasIssues = (preview?.issues.length ?? 0) > 0

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('assets.importTitle')}</DialogTitle>
          <DialogDescription>{t('assets.importDescription')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="asset-import-file">{t('assets.importFile')}</Label>
            <Input
              id="asset-import-file"
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.xlsm"
              disabled={importEquipment.isPending}
              onChange={(e) => void handleFileSelect(e.target.files?.[0])}
            />
            {fileName && (
              <p className="text-xs text-muted-foreground">{fileName}</p>
            )}
          </div>

          {importEquipment.isPending && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoadingSpinner size="sm" />
              {t('assets.importValidating')}
            </div>
          )}

          {preview && !importEquipment.isPending && (
            <div className="space-y-3">
              <Alert variant={hasIssues ? 'default' : undefined}>
                {hasIssues ? (
                  <AlertCircle className="h-4 w-4" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                <AlertTitle>
                  {confirmed
                    ? t('assets.importSuccess', { count: preview.imported_count })
                    : t('assets.importPreviewTitle', {
                        valid: preview.valid_rows.length,
                        total: preview.total_rows,
                      })}
                </AlertTitle>
                <AlertDescription>
                  {confirmed
                    ? t('assets.importSkipped', { count: preview.issues.length })
                    : t('assets.importPreviewHint')}
                </AlertDescription>
              </Alert>

              {preview.valid_rows.length > 0 && !confirmed && (
                <div className="max-h-40 overflow-auto rounded-md border">
                  <table className="w-full text-sm">
                    <tbody>
                      {preview.valid_rows.slice(0, 20).map((row) => (
                        <tr key={row.row_number} className="border-b last:border-0">
                          <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">
                            {row.row_number}
                          </td>
                          <td className="px-3 py-1.5 font-medium">{row.code}</td>
                          <td className="px-3 py-1.5 text-muted-foreground truncate max-w-[260px]">
                            {row.name}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {preview.valid_rows.length > 20 && (
                    <p className="px-3 py-1.5 text-xs text-muted-foreground">
                      {t('assets.importMoreRows', { count: preview.valid_rows.length - 20 })}
                    </p>
                  )}
                </div>
              )}

              {hasIssues && (
                <div className="max-h-40 overflow-auto rounded-md border border-destructive/30">
                  <table className="w-full text-sm">
                    <tbody>
                      {preview.issues.map((issue, idx) => (
                        <tr key={`${issue.row_number}-${idx}`} className="border-b last:border-0">
                          <td className="px-3 py-1.5 font-mono text-xs text-muted-foreground">
                            {issue.row_number}
                          </td>
                          <td className="px-3 py-1.5 font-medium">
                            {issue.code || '—'}
                          </td>
                          <td className="px-3 py-1.5 text-destructive">
                            {issue.message}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={closeDialog}>
            {confirmed ? t('common.close') : t('common.cancel')}
          </Button>
          {!confirmed && (
            <Button
              type="button"
              onClick={() => void handleConfirm()}
              disabled={
                !preview || preview.valid_rows.length === 0 || importEquipment.isPending
              }
            >
              <FileSpreadsheet className="h-4 w-4 me-2" />
              {t('assets.importConfirm')}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
