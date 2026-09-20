import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, act, waitFor } from '@testing-library/react'
import { I18nProvider } from './I18nProvider'
import i18n from '@/lib/i18n'

describe('I18nProvider document direction', () => {
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
})
