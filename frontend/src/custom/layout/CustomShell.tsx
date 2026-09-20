'use client'

import { CustomSidebar } from './CustomSidebar'
import { SetupBanner } from '@/components/layout/SetupBanner'

interface CustomShellProps {
  children: React.ReactNode
}

/**
 * Downstream shell. Same layout contract as the upstream AppShell
 * (sidebar + main column with setup banner + content) so routing,
 * authentication, provider, responsive, and banner behavior are preserved.
 */
export function CustomShell({ children }: CustomShellProps) {
  return (
    <div className="custom-shell flex h-screen overflow-hidden bg-[var(--custom-page)] text-[var(--custom-foreground)]">
      <CustomSidebar />
      <main className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <SetupBanner />
        {children}
      </main>
    </div>
  )
}
