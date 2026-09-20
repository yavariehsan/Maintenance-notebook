import { describe, it, expect, beforeEach, afterEach, beforeAll, vi } from 'vitest'
import { render, screen, act, waitFor } from '@testing-library/react'
import { I18nProvider } from './I18nProvider'
import i18n from '@/lib/i18n'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

describe('I18nProvider document direction', () => {
  beforeAll(() => {
    // jsdom does not implement scrollIntoView (used by Radix Select).
    Element.prototype.scrollIntoView = vi.fn()
  })

  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.lang = 'en'
    document.documentElement.dir = 'ltr'
  })

  afterEach(async () => {
    await i18n.changeLanguage('en')
    window.localStorage.clear()
    document.documentElement.lang = 'en'
    document.documentElement.dir = 'ltr'
  })

  it('renders English LTR by default', async () => {
    render(
      <I18nProvider>
        <div>child</div>
      </I18nProvider>,
    )

    await waitFor(() => expect(screen.getByText('child')).toBeVisible())
    expect(document.documentElement.lang).toBe('en')
    expect(document.documentElement.dir).toBe('ltr')
  })

  it('switches en -> fa to RTL and fa -> en back to LTR', async () => {
    render(
      <I18nProvider>
        <div>child</div>
      </I18nProvider>,
    )
    await waitFor(() => expect(screen.getByText('child')).toBeVisible())

    await act(async () => {
      await i18n.changeLanguage('fa')
    })
    expect(i18n.language).toBe('fa')
    expect(document.documentElement.lang).toBe('fa')
    expect(document.documentElement.dir).toBe('rtl')
    // Persisted for reload.
    expect(window.localStorage.getItem('i18nextLng')).toBe('fa')

    await act(async () => {
      await i18n.changeLanguage('en')
    })
    expect(document.documentElement.lang).toBe('en')
    expect(document.documentElement.dir).toBe('ltr')
    expect(window.localStorage.getItem('i18nextLng')).toBe('en')
  })

  it('migrates a removed persisted locale to English on init', async () => {
    vi.resetModules()
    window.localStorage.setItem('i18nextLng', 'de-DE')
    await import('@/lib/i18n')
    expect(window.localStorage.getItem('i18nextLng')).toBe('en')
  })

  it('propagates locale direction into Radix primitives (no LTR islands)', async () => {
    render(
      <I18nProvider>
        <Select defaultOpen value="a">
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="a">Alpha</SelectItem>
          </SelectContent>
        </Select>
      </I18nProvider>,
    )
    await waitFor(() => expect(screen.getByRole('listbox')).toBeDefined())

    // English: Radix content follows the locale (ltr here, not a hard-coded island).
    expect(document.querySelector('[role="listbox"]')?.closest('[dir="ltr"]')).not.toBeNull()

    await act(async () => {
      await i18n.changeLanguage('fa')
    })
    expect(
      document.querySelector('[role="listbox"]')?.closest('[dir="rtl"]'),
    ).not.toBeNull()
  })
})
