import { describe, it, expect } from 'vitest'
import {
  resources,
  languages,
  languageDirections,
  getLanguageDirection,
  isSupportedLanguage,
  normalizeLanguage,
  FALLBACK_LANGUAGE,
  SUPPORTED_LANGUAGES,
} from './index'
import { en } from './en'
import { fa } from './fa'

describe('Supported locales', () => {
  it('exposes exactly en and fa resources', () => {
    expect(Object.keys(resources).sort()).toEqual(['en', 'fa'])
  })

  it('lists only English and Persian in the selector config', () => {
    expect(languages).toEqual([
      { code: 'en', label: 'English' },
      { code: 'fa', label: 'فارسی' },
    ])
  })

  it('keeps SUPPORTED_LANGUAGES in sync with resources', () => {
    expect([...SUPPORTED_LANGUAGES].sort()).toEqual(Object.keys(resources).sort())
  })

  it('rejects removed locales', () => {
    for (const code of [
      'en-US',
      'de-DE',
      'fr-FR',
      'zh-CN',
      'zh-TW',
      'pt-BR',
      'ja-JP',
      'it-IT',
      'ru-RU',
      'bn-IN',
      'ca-ES',
      'es-ES',
      'pl-PL',
      'tr-TR',
    ]) {
      expect(isSupportedLanguage(code)).toBe(false)
    }
    expect(isSupportedLanguage('en')).toBe(true)
    expect(isSupportedLanguage('fa')).toBe(true)
  })

  it('falls back to English', () => {
    expect(FALLBACK_LANGUAGE).toBe('en')
  })
})

describe('Language direction', () => {
  it('maps en to ltr and fa to rtl', () => {
    expect(languageDirections).toEqual({ en: 'ltr', fa: 'rtl' })
    expect(getLanguageDirection('en')).toBe('ltr')
    expect(getLanguageDirection('fa')).toBe('rtl')
  })

  it('resolves region variants by language', () => {
    expect(getLanguageDirection('fa-IR')).toBe('rtl')
    expect(getLanguageDirection('en-US')).toBe('ltr')
  })

  it('falls back to ltr for unknown or missing codes', () => {
    expect(getLanguageDirection('de-DE')).toBe('ltr')
    expect(getLanguageDirection(null)).toBe('ltr')
    expect(getLanguageDirection(undefined)).toBe('ltr')
    expect(getLanguageDirection('')).toBe('ltr')
  })
})

describe('normalizeLanguage', () => {  it('keeps supported codes', () => {
    expect(normalizeLanguage('en')).toBe('en')
    expect(normalizeLanguage('fa')).toBe('fa')
  })

  it('keeps the language of legacy region codes', () => {
    expect(normalizeLanguage('en-US')).toBe('en')
    expect(normalizeLanguage('fa-IR')).toBe('fa')
  })

  it('migrates removed locales to English', () => {
    for (const code of ['de-DE', 'zh-CN', 'pt-BR', 'tr-TR', 'xx']) {
      expect(normalizeLanguage(code)).toBe('en')
    }
  })

  it('migrates missing values to English', () => {
    expect(normalizeLanguage(null)).toBe('en')
    expect(normalizeLanguage(undefined)).toBe('en')
    expect(normalizeLanguage('')).toBe('en')
  })
})

const BRAND = 'Maintenance AI Agent'

const collectLeaves = (obj: Record<string, unknown>): string[] => {
  const out: string[] = []
  for (const val of Object.values(obj)) {
    if (typeof val === 'string') out.push(val)
    else if (typeof val === 'object' && val !== null && !Array.isArray(val)) {
      out.push(...collectLeaves(val as Record<string, unknown>))
    }
  }
  return out
}

describe('Product branding', () => {
  it('brands the app as Maintenance AI Agent in English', () => {
    expect(en.common.appName).toBe(BRAND)
    expect(en.auth.loginTitle).toBe(BRAND)
  })

  it('brands the app as Maintenance AI Agent in Persian', () => {
    expect(fa.common.appName).toBe(BRAND)
    expect(fa.auth.loginTitle).toBe(BRAND)
    expect(fa.connectionErrors.docLink).toContain(BRAND)
  })

  it('contains no legacy Open Notebook user-visible strings', () => {
    for (const [code, locale] of [
      ['en', en],
      ['fa', fa],
    ] as const) {
      const hits = collectLeaves(locale as unknown as Record<string, unknown>).filter(
        (v) => v.includes('Open Notebook'),
      )
      expect(hits, `Legacy branding in ${code}: ${hits.join(' | ')}`).toEqual([])
    }
  })
})
