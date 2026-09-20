'use client'

import { AppShell } from '@/components/layout/AppShell'
import { SettingsForm } from '@/app/(dashboard)/settings/components/SettingsForm'
import { Button } from '@/components/ui/button'
import { RefreshCw } from 'lucide-react'
import { useSettings } from '@/lib/hooks/use-settings'
import { useTranslation } from '@/lib/hooks/use-translation'

/**
 * Downstream Settings screen. Owns page composition (header, layout
 * container, theme) while reusing the upstream SettingsForm — the RHF/zod
 * form with capability gating stays canonical upstream, mirroring how
 * ModelsScreen reuses ProviderSection. No second API client, validation,
 * or form framework.
 */
export function SettingsScreen() {
  const { t } = useTranslation()
  const { refetch } = useSettings()

  return (
    <AppShell>
      <div className="flex-1 overflow-y-auto bg-[var(--custom-page)] text-[var(--custom-foreground)]">
        <div className="p-6">
          <div className="max-w-4xl">
            <div className="flex items-center gap-4 mb-6">
              <h1 className="font-display text-2xl font-bold tracking-tight">{t('navigation.settings')}</h1>
              <Button variant="outline" size="sm" onClick={() => refetch()}>
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>

            <SettingsForm />
          </div>
        </div>
      </div>
    </AppShell>
  )
}
