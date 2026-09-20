import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'
import { CustomSidebar } from './CustomSidebar'

// Controllable language per test (overrides the global setup mock).
vi.mock('@/lib/hooks/use-translation', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    language: (globalThis as { __testLang?: string }).__testLang ?? 'en',
    setLanguage: vi.fn(),
  }),
}))

function setTestLanguage(lang: string) {
  ;(globalThis as { __testLang?: string }).__testLang = lang
}

describe('CustomSidebar direction', () => {
  it('uses the LTR collapse chevron and left-anchored UI in English', () => {
    setTestLanguage('en')
    const { container } = render(<CustomSidebar />)

    // Collapse toggle points left when the sidebar is on the left.
    expect(
      container.querySelector('[data-testid="sidebar-toggle"] svg.lucide-chevron-left'),
    ).not.toBeNull()
    expect(
      container.querySelector('[data-testid="sidebar-toggle"] svg.lucide-chevron-right'),
    ).toBeNull()
    // Inner-edge border follows the inline end (right in LTR).
    expect(container.querySelector('.custom-sidebar')?.className).toContain('border-e')
  })

  it('mirrors the collapse chevron in Persian (sidebar on the right)', () => {
    setTestLanguage('fa')
    const { container } = render(<CustomSidebar />)

    expect(
      container.querySelector('[data-testid="sidebar-toggle"] svg.lucide-chevron-right'),
    ).not.toBeNull()
    expect(
      container.querySelector('[data-testid="sidebar-toggle"] svg.lucide-chevron-left'),
    ).toBeNull()
  })

  it('keeps the nav region scrollable and the footer pinned in both directions', () => {
    for (const lang of ['en', 'fa']) {
      setTestLanguage(lang)
      const { container, unmount } = render(<CustomSidebar />)
      // Root cause of clipped Sign Out: nav must shrink inside the fixed
      // sidebar height and scroll instead of pushing the footer out.
      const nav = container.querySelector('nav')
      expect(nav?.className).toContain('min-h-0')
      expect(nav?.className).toContain('overflow-y-auto')
      // Footer (theme/language/logout) must stay reachable at any height.
      const signOut = container.querySelector('[aria-label="common.signOut"]')
      const footer = signOut?.closest('div')
      expect(footer?.className).toContain('shrink-0')
      unmount()
    }
  })

  it('keeps navigation and actions functional in both directions', () => {    for (const lang of ['en', 'fa']) {
      setTestLanguage(lang)
      const { container, unmount } = render(<CustomSidebar />)
      // Nav links, create menu trigger, and logout are all present.
      expect(container.querySelector('a[href="/sources"]')).not.toBeNull()
      expect(container.querySelector('a[href="/assets"]')).not.toBeNull()
      expect(container.querySelector('a[href="/notebooks"]')).not.toBeNull()
      expect(container.querySelector('[aria-label="common.signOut"]')).not.toBeNull()
      unmount()
    }
  })
})
