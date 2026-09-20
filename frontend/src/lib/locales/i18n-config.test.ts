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

describe('normalizeLanguage', () => {
  it('keeps supported codes', () => {
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
