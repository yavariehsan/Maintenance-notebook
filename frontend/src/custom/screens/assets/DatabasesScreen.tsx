'use client'

import { useState } from 'react'

import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { useTranslation } from '@/lib/hooks/use-translation'
import { AssetRegistryScreen } from './AssetRegistryScreen'
import { FailureModesSection } from './FailureModesSection'

type DatabaseTab = 'equipment' | 'failureModes'

/**
 * Database section (دیتابیس) with two independent subsections sharing
 * one route: the equipment-information database (existing asset
 * registry, unchanged behavior) and the failure-mode database (new
 * dedicated `failure_mode` table). Tab state is local; each tab owns
 * its own API endpoints, so writes can never cross databases.
 */
export function DatabasesScreen({ initialTab = 'equipment' }: { initialTab?: DatabaseTab }) {
  const { t } = useTranslation()
  const [tab, setTab] = useState<DatabaseTab>(initialTab)

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-[var(--custom-page)] text-[var(--custom-foreground)]">
        <div className="p-6 space-y-6">
          <div>
            <h1 className="font-display text-2xl font-bold tracking-tight">{t('databases.title')}</h1>
            <p className="mt-1 text-sm text-muted-foreground">{t('databases.description')}</p>
          </div>

          <div className="flex gap-2" role="tablist" aria-label={t('databases.title')}>
            <Button
              role="tab"
              aria-selected={tab === 'equipment'}
              variant={tab === 'equipment' ? 'default' : 'outline'}
              onClick={() => setTab('equipment')}
            >
              {t('databases.equipmentTab')}
            </Button>
            <Button
              role="tab"
              aria-selected={tab === 'failureModes'}
              variant={tab === 'failureModes' ? 'default' : 'outline'}
              onClick={() => setTab('failureModes')}
            >
              {t('databases.failureModesTab')}
            </Button>
          </div>

          {tab === 'equipment' ? <AssetRegistryScreen /> : <FailureModesSection />}
        </div>
      </div>
    </AppShell>
  )
}
