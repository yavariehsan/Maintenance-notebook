import { en } from './en';
import { fa } from './fa';

export const resources = {
  en: { translation: en },
  fa: { translation: fa },
} as const;

export type TranslationKeys = typeof en;

export type LanguageCode = keyof typeof resources;

export const SUPPORTED_LANGUAGES: readonly LanguageCode[] = ['en', 'fa'];

export function isSupportedLanguage(code: string | null | undefined): code is LanguageCode {
  return code === 'en' || code === 'fa';
}

/** Fallback locale used for unsupported or legacy stored values. */
export const FALLBACK_LANGUAGE: LanguageCode = 'en';

/**
 * Normalize any stored/detected language value to a supported code.
 * Legacy region codes ('en-US') keep their language; removed locales
 * ('de-DE', 'zh-CN', ...) safely fall back to English.
 */
export function normalizeLanguage(code: string | null | undefined): LanguageCode {
  if (!code) return FALLBACK_LANGUAGE;
  const lower = code.toLowerCase();
  if (lower === 'fa' || lower.startsWith('fa-')) return 'fa';
  if (lower === 'en' || lower.startsWith('en-')) return 'en';
  return FALLBACK_LANGUAGE;
}

export type Language = {
  code: LanguageCode;
  label: string;
};

export const languages: Language[] = [
  { code: 'en', label: 'English' },
  { code: 'fa', label: 'فارسی' },
];

export type TextDirection = 'ltr' | 'rtl';

export const languageDirections: Record<LanguageCode, TextDirection> = {
  en: 'ltr',
  fa: 'rtl',
};

/** Document direction for a language code; unknown codes fall back to English (ltr). */
export function getLanguageDirection(code: string | null | undefined): TextDirection {
  if (code === 'fa' || code?.startsWith('fa')) return 'rtl';
  return 'ltr';
}

export { en, fa };
