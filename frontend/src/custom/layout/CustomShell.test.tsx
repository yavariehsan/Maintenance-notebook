/* eslint-disable @typescript-eslint/no-explicit-any */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { usePathname } from 'next/navigation'
import { CustomShell } from './CustomShell'
import { useSidebarStore } from '@/lib/stores/sidebar-store'

// Mock Tooltip components to avoid Radix UI async issues in tests
vi.mock('@/components/ui/tooltip', () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// SetupBanner performs API queries; shell layout is what matters here
vi.mock('@/components/layout/SetupBanner', () => ({
  SetupBanner: () => null,
}))

describe('CustomShell', () => {
  it('renders children inside the shell layout', () => {
    const { container } = render(
      <CustomShell>
        <div>downstream content</div>
      </CustomShell>
    )

    expect(screen.getByText('downstream content')).toBeDefined()
    expect(container.querySelector('.custom-shell')).not.toBeNull()
  })

  it('renders downstream navigation with upstream route semantics', () => {
    vi.mocked(usePathname).mockReturnValue('/notebooks')
    const { container } = render(
      <CustomShell>
        <div>content</div>
      </CustomShell>
    )

    expect(container.querySelector('a[href="/notebooks"]')).not.toBeNull()
    expect(container.querySelector('a[href="/sources"]')).not.toBeNull()
    expect(container.querySelector('a[href="/search"]')).not.toBeNull()
    const active = container.querySelector('a[href="/notebooks"] button')
    expect(active?.className).toContain('font-semibold')
  })

  it('delegates collapse behavior to the existing sidebar store', () => {
    const toggleCollapse = vi.fn()
    vi.mocked(useSidebarStore).mockReturnValue({
      isCollapsed: false,
      toggleCollapse,
    } as any)

    render(
      <CustomShell>
        <div>content</div>
      </CustomShell>
    )

    fireEvent.click(screen.getByTestId('sidebar-toggle'))
    expect(toggleCollapse).toHaveBeenCalled()
  })
})
