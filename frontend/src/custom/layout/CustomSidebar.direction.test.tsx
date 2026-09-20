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

  it('keeps navigation and actions functional in both directions', () => {
    for (const lang of ['en', 'fa']) {
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
