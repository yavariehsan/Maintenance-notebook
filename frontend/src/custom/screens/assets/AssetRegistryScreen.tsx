'use client'

import { Fragment, useState } from 'react'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertCircle, ChevronDown, Cog, FileSpreadsheet, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useAssets, useCreateAsset, useDeleteAsset, useUpdateAsset } from '@/lib/hooks/use-assets'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { AssetResponse, CreateAssetRequest } from '@/lib/types/api'
import { AssetDialog } from './AssetDialog'
import { AssetImportDialog } from './AssetImportDialog'

/**
 * Downstream Asset Registry screen. Owns equipment composition (list,
 * create/edit dialog, delete confirmation) while reusing upstream asset
 * infrastructure: assetsApi via hooks, ConfirmDialog, and UI primitives.
 */
function AssetDetail({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="truncate font-medium">{value || '—'}</dd>
    </div>
  )
}

export function AssetRegistryScreen() {
  const { t } = useTranslation()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [editing, setEditing] = useState<AssetResponse | null>(null)
  const [deleting, setDeleting] = useState<AssetResponse | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const { data: assets, isLoading, isError, refetch } = useAssets()
  const createAsset = useCreateAsset()
  const updateAsset = useUpdateAsset()
  const deleteAsset = useDeleteAsset()

  const openCreate = () => {
    setEditing(null)
    setDialogOpen(true)
  }

  const openEdit = (asset: AssetResponse) => {
    setEditing(asset)
    setDialogOpen(true)
  }

  const handleSubmit = async (data: CreateAssetRequest) => {
    if (editing) {
      await updateAsset.mutateAsync({ id: editing.id, data })
    } else {
      await createAsset.mutateAsync(data)
    }
  }

  const handleDeleteConfirm = async () => {
    if (!deleting) return
    await deleteAsset.mutateAsync(deleting.id)
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
            <span>{t('assets.loadFailed')}</span>
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

    if (!assets || assets.length === 0) {
      return (
        <EmptyState
          icon={Cog}
          title={t('assets.emptyTitle')}
          description={t('assets.emptyDescription')}
          action={
            <div className="mt-4 flex flex-col sm:flex-row gap-2">
              <Button onClick={() => setImportOpen(true)} variant="outline">
                <FileSpreadsheet className="h-4 w-4 me-2" />
                {t('assets.importButton')}
              </Button>
              <Button onClick={openCreate} variant="outline">
                <Plus className="h-4 w-4 me-2" />
                {t('assets.newAsset')}
              </Button>
            </div>
          }
        />
      )
    }

    return (
      <div className="rounded-md border border-[var(--custom-border)] bg-[var(--custom-surface)] overflow-auto">
        <table className="w-full min-w-[880px] outline-none table-fixed">
          <colgroup>
            <col className="w-[110px]" />
            <col className="w-auto" />
            <col className="w-[120px]" />
            <col className="w-[110px]" />
            <col className="w-[140px] hidden sm:table-column" />
            <col className="w-[150px]" />
          </colgroup>
          <thead className="sticky top-0 bg-background z-10">
            <tr className="border-b">
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('assets.code')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('common.name')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('common.type')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground">
                {t('assets.status')}
              </th>
              <th className="h-12 px-4 text-start align-middle font-medium text-muted-foreground hidden sm:table-cell">
                {t('assets.location')}
              </th>
              <th className="h-12 px-4 text-end align-middle font-medium text-muted-foreground">
                {t('common.actions')}
              </th>
            </tr>
          </thead>
          <tbody>
            {assets.map((asset) => (
              <Fragment key={asset.id}>
                <tr className="border-b transition-colors hover:bg-[var(--surface-raised)]">
                  <td className="h-12 px-4">
                    <span className="font-mono text-sm font-medium">{asset.code || '—'}</span>
                  </td>
                  <td className="h-12 px-4">
                    <div className="flex flex-col overflow-hidden">
                      <span className="font-medium truncate">{asset.name}</span>
                      <span className="text-xs text-muted-foreground truncate">
                        {[asset.manufacturer, asset.model].filter(Boolean).join(' · ') || asset.description || ''}
                      </span>
                    </div>
                  </td>
                  <td className="h-12 px-4 text-sm text-muted-foreground truncate">
                    {asset.asset_type || '—'}
                  </td>
                  <td className="h-12 px-4">
                    <Badge variant="secondary" className="font-mono text-[11px]">
                      {asset.status}
                    </Badge>
                  </td>
                  <td className="h-12 px-4 text-sm text-muted-foreground truncate hidden sm:table-cell">
                    {asset.location || '—'}
                  </td>
                  <td className="h-12 px-4 text-end">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setExpandedId(expandedId === asset.id ? null : asset.id)}
                        aria-label={t('assets.toggleDetails')}
                        aria-expanded={expandedId === asset.id}
                      >
                        <ChevronDown
                          className={`h-4 w-4 transition-transform ${expandedId === asset.id ? 'rotate-180' : ''}`}
                        />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => openEdit(asset)}
                        aria-label={t('assets.editAsset')}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setDeleting(asset)}
                        aria-label={t('assets.deleteTitle')}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
                {expandedId === asset.id && (
                  <tr className="border-b bg-[var(--surface-raised)]">
                    <td colSpan={6} className="px-4 py-3">
                      <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-6 gap-y-2 text-sm">
                        <AssetDetail label={t('assets.code')} value={asset.code} />
                        <AssetDetail label={t('common.name')} value={asset.name} />
                        <AssetDetail label={t('common.description')} value={asset.description} />
                        <AssetDetail label={t('assets.factory')} value={asset.factory} />
                        <AssetDetail label={t('assets.location')} value={asset.location} />
                        <AssetDetail label={t('assets.zone')} value={asset.zone_description} />
                        <AssetDetail label={t('assets.site')} value={asset.site_description} />
                        <AssetDetail label={t('assets.plant')} value={asset.plant_description} />
                        <AssetDetail label={t('assets.mainClass')} value={asset.main_class} />
                        <AssetDetail label={t('assets.subClass')} value={asset.sub_class} />
                        <AssetDetail label={t('common.type')} value={asset.asset_type} />
                        <AssetDetail label={t('assets.manufacturer')} value={asset.manufacturer} />
                        <AssetDetail label={t('assets.model')} value={asset.model} />
                        <AssetDetail label={t('assets.serialNumber')} value={asset.serial_number} />
                        <AssetDetail label={t('assets.status')} value={asset.status} />
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-[var(--custom-page)] text-[var(--custom-foreground)]">
        <div className="p-6 space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="font-display text-2xl font-bold tracking-tight">{t('assets.title')}</h1>
              <p className="mt-1 text-sm text-muted-foreground">{t('assets.description')}</p>
            </div>
            {assets && assets.length > 0 && (
              <div className="flex gap-2">
                <Button onClick={() => setImportOpen(true)} variant="outline">
                  <FileSpreadsheet className="h-4 w-4 me-2" />
                  {t('assets.importButton')}
                </Button>
                <Button onClick={openCreate}>
                  <Plus className="h-4 w-4 me-2" />
                  {t('assets.newAsset')}
                </Button>
              </div>
            )}
          </div>

          {renderContent()}
        </div>
      </div>

      <AssetDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        asset={editing}
        onSubmit={handleSubmit}
        isPending={createAsset.isPending || updateAsset.isPending}
      />

      <AssetImportDialog open={importOpen} onOpenChange={setImportOpen} />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null)
        }}
        title={t('assets.deleteTitle')}
        description={t('assets.deleteConfirm', { name: deleting?.name ?? '' })}
        confirmText={t('common.delete')}
        confirmVariant="destructive"
        onConfirm={handleDeleteConfirm}
      />
    </AppShell>
  )
}
