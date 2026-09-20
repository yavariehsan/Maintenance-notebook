import { enUS, faIR, Locale } from 'date-fns/locale'

/**
 * Mapping of language codes to date-fns locales.
 */
const LOCALE_MAP: Record<string, Locale> = {
  en: enUS,
  fa: faIR,
}

/**
 * Get the date-fns locale for a given language code.
 * Falls back to English if the language is not found.
 *
 * @param language - The language code (e.g., 'en', 'fa')
 * @returns The corresponding date-fns Locale object
 */
export function getDateLocale(language: string): Locale {
  return LOCALE_MAP[language] || enUS
}
