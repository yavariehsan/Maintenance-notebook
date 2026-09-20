'use client'

import { useEffect } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'

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
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { AssetResponse, CreateAssetRequest } from '@/lib/types/api'

const assetSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  description: z.string().optional(),
  asset_type: z.string().optional(),
  status: z.string().optional(),
  location: z.string().optional(),
  manufacturer: z.string().optional(),
  model: z.string().optional(),
  serial_number: z.string().optional(),
})

type AssetFormData = z.infer<typeof assetSchema>

interface AssetDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  asset?: AssetResponse | null
  onSubmit: (data: CreateAssetRequest) => Promise<void> | void
  isPending: boolean
}

const emptyValues: AssetFormData = {
  name: '',
  description: '',
  asset_type: '',
  status: 'active',
  location: '',
  manufacturer: '',
  model: '',
  serial_number: '',
}

export function AssetDialog({ open, onOpenChange, asset, onSubmit, isPending }: AssetDialogProps) {
  const { t } = useTranslation()
  const {
    register,
    handleSubmit,
    formState: { errors, isValid },
    reset,
  } = useForm<AssetFormData>({
    resolver: zodResolver(assetSchema),
    mode: 'onChange',
    defaultValues: emptyValues,
  })

  useEffect(() => {
    if (open) {
      reset(
        asset
          ? {
              name: asset.name,
              description: asset.description ?? '',
              asset_type: asset.asset_type ?? '',
              status: asset.status ?? 'active',
              location: asset.location ?? '',
              manufacturer: asset.manufacturer ?? '',
              model: asset.model ?? '',
              serial_number: asset.serial_number ?? '',
            }
          : emptyValues
      )
    }
  }, [open, asset, reset])

  const closeDialog = () => onOpenChange(false)

  const submit = async (data: AssetFormData) => {
    const payload: CreateAssetRequest = {
      name: data.name.trim(),
      description: data.description?.trim() || '',
      asset_type: data.asset_type?.trim() || null,
      status: data.status?.trim() || 'active',
      location: data.location?.trim() || null,
      manufacturer: data.manufacturer?.trim() || null,
      model: data.model?.trim() || null,
      serial_number: data.serial_number?.trim() || null,
    }
    await onSubmit(payload)
    closeDialog()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>{asset ? t('assets.editAsset') : t('assets.newAsset')}</DialogTitle>
          <DialogDescription>{t('assets.description')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(submit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="asset-name">{t('common.name')}</Label>
            <Input
              id="asset-name"
              {...register('name')}
              placeholder={t('assets.newAsset')}
              autoComplete="off"
              disabled={isPending}
            />
            {errors.name && (
              <p className="text-sm text-destructive">{errors.name.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="asset-description">{t('common.description')}</Label>
            <Textarea
              id="asset-description"
              {...register('description')}
              disabled={isPending}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="asset-type">{t('common.type')}</Label>
              <Input id="asset-type" {...register('asset_type')} autoComplete="off" disabled={isPending} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="asset-status">{t('assets.status')}</Label>
              <Input id="asset-status" {...register('status')} autoComplete="off" disabled={isPending} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="asset-location">{t('assets.location')}</Label>
              <Input id="asset-location" {...register('location')} autoComplete="off" disabled={isPending} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="asset-manufacturer">{t('assets.manufacturer')}</Label>
              <Input id="asset-manufacturer" {...register('manufacturer')} autoComplete="off" disabled={isPending} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="asset-model">{t('assets.model')}</Label>
              <Input id="asset-model" {...register('model')} autoComplete="off" disabled={isPending} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="asset-serial">{t('assets.serialNumber')}</Label>
              <Input id="asset-serial" {...register('serial_number')} autoComplete="off" disabled={isPending} />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={closeDialog} disabled={isPending}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={!isValid || isPending}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
