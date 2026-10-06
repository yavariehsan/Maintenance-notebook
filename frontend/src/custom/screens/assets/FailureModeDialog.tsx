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
import type { CreateFailureModeRequest, FailureModeResponse } from '@/lib/types/api'

const failureModeSchema = z.object({
  code: z.string().min(1, 'Code is required'),
  label: z.string().min(1, 'Failure mode is required'),
  description: z.string().optional(),
  status: z.string().optional(),
})

type FailureModeFormData = z.infer<typeof failureModeSchema>

interface FailureModeDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  mode?: FailureModeResponse | null
  onSubmit: (data: CreateFailureModeRequest) => Promise<void> | void
  isPending: boolean
}

const emptyValues: FailureModeFormData = {
  code: '',
  label: '',
  description: '',
  status: 'active',
}

export function FailureModeDialog({ open, onOpenChange, mode, onSubmit, isPending }: FailureModeDialogProps) {
  const { t } = useTranslation()
  const {
    register,
    handleSubmit,
    formState: { errors, isValid },
    reset,
  } = useForm<FailureModeFormData>({
    resolver: zodResolver(failureModeSchema),
    mode: 'onChange',
    defaultValues: emptyValues,
  })

  useEffect(() => {
    if (open) {
      reset(
        mode
          ? {
              code: mode.code ?? '',
              label: mode.label ?? '',
              description: mode.description ?? '',
              status: mode.status ?? 'active',
            }
          : emptyValues
      )
    }
  }, [open, mode, reset])

  const closeDialog = () => onOpenChange(false)

  const submit = async (data: FailureModeFormData) => {
    const payload: CreateFailureModeRequest = {
      code: data.code.trim(),
      label: data.label.trim(),
      description: data.description?.trim() || '',
      status: data.status?.trim() || 'active',
    }
    await onSubmit(payload)
    closeDialog()
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px] max-h-[90vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>{mode ? t('failureModes.editMode') : t('failureModes.newModeTitle')}</DialogTitle>
          <DialogDescription>{t('failureModes.description')}</DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(submit)} className="flex flex-col min-h-0 flex-1">
          <div className="flex-1 min-h-0 overflow-y-auto space-y-4 pe-1">
            <div className="space-y-2">
              <Label htmlFor="failure-mode-code">{t('failureModes.code')}</Label>
              <Input
                id="failure-mode-code"
                {...register('code')}
                autoComplete="off"
                disabled={isPending}
              />
              {errors.code && (
                <p className="text-sm text-destructive">{errors.code.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="failure-mode-label">{t('failureModes.label')}</Label>
              <Input
                id="failure-mode-label"
                {...register('label')}
                autoComplete="off"
                disabled={isPending}
              />
              {errors.label && (
                <p className="text-sm text-destructive">{errors.label.message}</p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="failure-mode-description">{t('failureModes.descriptionField')}</Label>
              <Textarea
                id="failure-mode-description"
                {...register('description')}
                disabled={isPending}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="failure-mode-status">{t('failureModes.status')}</Label>
              <Input
                id="failure-mode-status"
                {...register('status')}
                autoComplete="off"
                disabled={isPending}
              />
            </div>
          </div>

          <DialogFooter className="pt-4">
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
