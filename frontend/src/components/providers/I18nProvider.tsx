'use client'

import React, { useEffect, useState } from 'react'
import { DirectionProvider } from '@radix-ui/react-direction'
import i18n from '@/lib/i18n'
import { getLanguageDirection, type TextDirection } from '@/lib/locales'
import { LanguageLoadingOverlay } from '@/components/common/LanguageLoadingOverlay'

/**
 * Keeps the document <html> lang/dir attributes in sync with the active
 * locale: en -> lang="en" dir="ltr", fa -> lang="fa" dir="rtl".
 * The <html> element is the authoritative direction for the whole app,
 * so flex layouts (including the sidebar shell) flip automatically in RTL.
 */
function useLocaleDirection(onChange: (direction: TextDirection) => void) {
  useEffect(() => {
    const apply = (lng: string) => {
      const code = lng?.startsWith('fa') ? 'fa' : 'en'
      const direction = getLanguageDirection(code)
      document.documentElement.lang = code
      document.documentElement.dir = direction
      onChange(direction)
    }
    apply(i18n.language)
    i18n.on('languageChanged', apply)
    return () => {
      i18n.off('languageChanged', apply)
    }
  }, [onChange])
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false)
  // Radix primitives (Select, DropdownMenu, Tooltip, Popover, Dialog) render
  // their own dir attribute from a Direction context that defaults to ltr,
  // which would leave LTR islands inside the RTL app. Mirror the locale.
  const [direction, setDirection] = useState<TextDirection>('ltr')

  useLocaleDirection(setDirection)

  useEffect(() => {
    setMounted(true)
  }, [])

  // Avoid hydration mismatch by waiting for mount
  if (!mounted) {
    return <div style={{ visibility: 'hidden' }}>{children}</div>
  }

  return (
    <DirectionProvider dir={direction}>
      <LanguageLoadingOverlay />
      {children}
    </DirectionProvider>
  )
}
