import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { resources, normalizeLanguage } from './locales'

const STORAGE_KEY = 'i18nextLng'

/**
 * Migrate legacy persisted locale values (e.g. removed locales like 'de-DE')
 * to a supported language. Runs before init so the detector never resolves
 * an unsupported stored value. SSR-safe: no localStorage access on server.
 */
function migrateStoredLanguage(): void {
  if (typeof window === 'undefined') return
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    const normalized = normalizeLanguage(stored)
    if (stored !== normalized) {
      window.localStorage.setItem(STORAGE_KEY, normalized)
    }
  } catch {
    // Storage unavailable (private mode, etc.) — detector falls back cleanly.
  }
}

migrateStoredLanguage()

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    supportedLngs: ['en', 'fa'],
    fallbackLng: 'en',
    // Strip region subtags so navigator values like 'en-US'/'fa-IR' resolve.
    load: 'languageOnly',
    interpolation: {
      escapeValue: false, // react already safes from xss
    },
    react: {
      useSuspense: false,
    },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
    },
  })

export default i18n
