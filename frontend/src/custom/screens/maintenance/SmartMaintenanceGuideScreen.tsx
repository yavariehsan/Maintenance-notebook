'use client'

import { useMemo, useState } from 'react'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { EmptyState } from '@/components/common/EmptyState'
import { LoadingSpinner } from '@/components/common/LoadingSpinner'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { AlertCircle, FileText, RefreshCw, Send, Stethoscope } from 'lucide-react'
import { useAssets } from '@/lib/hooks/use-assets'
import { useMaintenanceAsk, useMaintenanceSources } from '@/lib/hooks/use-maintenance'
import { useTranslation } from '@/lib/hooks/use-translation'
import type { AssetResponse, MaintenanceAskResponse } from '@/lib/types/api'

/**
 * Downstream Smart Maintenance Guide screen. Equipment selector (existing
 * assets API) + question input, answered strictly from the selected
 * equipment's CMMS sources via POST /api/maintenance/ask. Reuses upstream
 * AppShell, Select, query hooks, Alert/EmptyState, and UI primitives —
 * no second retrieval pipeline or application shell.
 */
function formatEquipmentOption(asset: AssetResponse): string {
  return [asset.code, asset.name, asset.manufacturer, asset.model]
    .filter(Boolean)
    .join(' — ')
}

export function SmartMaintenanceGuideScreen() {
  const { t } = useTranslation()
  const [selectedCode, setSelectedCode] = useState<string>('')
  const [question, setQuestion] = useState('')
  const [lastAnswer, setLastAnswer] = useState<MaintenanceAskResponse | null>(null)

  const {
    data: assets,
    isLoading: assetsLoading,
    isError: assetsError,
    refetch: refetchAssets,
  } = useAssets()
  const {
    data: cmmsSources,
    isLoading: sourcesLoading,
    isError: sourcesError,
    refetch: refetchSources,
  } = useMaintenanceSources(selectedCode || null)
  const askMutation = useMaintenanceAsk()

  const selectedAsset = useMemo(
    () => assets?.find((a) => (a.code ?? '') === selectedCode) ?? null,
    [assets, selectedCode]
  )

  const handleSelectCode = (code: string) => {
    setSelectedCode(code)
    setLastAnswer(null)
  }

  const handleAsk = async () => {
    if (!selectedCode || !question.trim() || askMutation.isPending) return
    const response = await askMutation.mutateAsync({
      equipment_code: selectedCode,
      question: question.trim(),
    })
    setLastAnswer(response)
  }

  const renderAnswer = () => {
    if (askMutation.isPending) {
      return (
        <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
          <LoadingSpinner size="sm" />
          {t('maintenance.answering')}
        </div>
      )
    }
    if (askMutation.isError) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('maintenance.askFailed')}</span>
            <Button variant="outline" size="sm" onClick={() => void handleAsk()} className="shrink-0">
              <RefreshCw className="h-4 w-4 me-2" />
              {t('common.retry')}
            </Button>
          </AlertDescription>
        </Alert>
      )
    }
    if (!lastAnswer) return null
    if (lastAnswer.status === 'no_sources') {
      return (
        <EmptyState
          icon={FileText}
          title={t('maintenance.noSourcesTitle')}
          description={t('maintenance.noSourcesDescription', { code: lastAnswer.equipment_code })}
        />
      )
    }
    if (lastAnswer.status === 'no_context') {
      return (
        <EmptyState
          icon={FileText}
          title={t('maintenance.noContextTitle')}
          description={t('maintenance.noContextDescription', { code: lastAnswer.equipment_code })}
        />
      )
    }
    return (
      <div className="space-y-4">
        <div className="whitespace-pre-wrap text-sm leading-7">{lastAnswer.answer}</div>
        {lastAnswer.sources.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-medium">{t('maintenance.sourcesTitle')}</h3>
            <ul className="flex flex-col gap-1.5">
              {lastAnswer.sources.map((source) => (
                <li key={source.id}>
                  <Badge variant="secondary" className="font-mono text-[11px]">
                    {source.title || source.id}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    )
  }

  const renderBody = () => {
    if (assetsLoading) {
      return (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner size="lg" />
        </div>
      )
    }
    if (assetsError) {
      return (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{t('common.error')}</AlertTitle>
          <AlertDescription className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <span>{t('maintenance.equipmentLoadFailed')}</span>
            <Button variant="outline" size="sm" onClick={() => refetchAssets()} className="shrink-0">
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
          icon={Stethoscope}
          title={t('maintenance.noEquipmentTitle')}
          description={t('maintenance.noEquipmentDescription')}
        />
      )
    }

    return (
      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('maintenance.selectEquipmentTitle')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="maintenance-equipment">{t('maintenance.equipmentLabel')}</Label>
              <Select value={selectedCode} onValueChange={handleSelectCode}>
                <SelectTrigger id="maintenance-equipment" className="w-full">
                  <SelectValue placeholder={t('maintenance.equipmentPlaceholder')} />
                </SelectTrigger>
                <SelectContent>
                  {assets
                    .filter((a) => a.code)
                    .map((asset) => (
                      <SelectItem key={asset.id} value={asset.code as string}>
                        {formatEquipmentOption(asset)}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>
            {selectedCode && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                {sourcesLoading ? (
                  <>
                    <LoadingSpinner size="sm" />
                    {t('maintenance.sourcesLoading')}
                  </>
                ) : sourcesError ? (
                  <Button variant="link" size="sm" onClick={() => refetchSources()}>
                    {t('maintenance.sourcesLoadFailed')}
                  </Button>
                ) : (
                  t('maintenance.sourcesCount', {
                    count: cmmsSources?.length ?? 0,
                    code: selectedCode,
                  })
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {selectedCode && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t('maintenance.askTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="maintenance-question">{t('maintenance.questionLabel')}</Label>
                <Textarea
                  id="maintenance-question"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder={t('maintenance.questionPlaceholder')}
                  rows={3}
                  disabled={askMutation.isPending}
                />
              </div>
              <Button
                onClick={() => void handleAsk()}
                disabled={!question.trim() || askMutation.isPending}
              >
                <Send className="h-4 w-4 me-2" />
                {t('maintenance.askButton')}
              </Button>
              {(askMutation.isPending || askMutation.isError || lastAnswer) && (
                <div className="border-t pt-4">{renderAnswer()}</div>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    )
  }

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-[var(--custom-page)] text-[var(--custom-foreground)]">
        <div className="p-6 space-y-6">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">{t('maintenance.title')}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t('maintenance.description')}</p>
          </div>
          {selectedAsset && (
            <p className="text-sm text-muted-foreground">
              {t('maintenance.selectedEquipment', {
                equipment: formatEquipmentOption(selectedAsset),
              })}
            </p>
          )}
          {renderBody()}
        </div>
      </div>
    </AppShell>
  )
}
