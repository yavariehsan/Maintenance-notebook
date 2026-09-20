'use client'

import { CustomShell } from '@/custom/layout/CustomShell'

interface AppShellProps {
  children: React.ReactNode
}

// Routing boundary stays here; presentation lives in CustomShell.
export function AppShell({ children }: AppShellProps) {
  return <CustomShell>{children}</CustomShell>
}
