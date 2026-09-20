'use client'

import React, { useEffect, useState } from 'react'
import i18n from '@/lib/i18n'
import { getLanguageDirection } from '@/lib/locales'
import { LanguageLoadingOverlay } from '@/components/common/LanguageLoadingOverlay'

/**
 * Keeps the document <html> lang/dir attributes in sync with the active
 * locale: en -> lang="en" dir="ltr", fa -> lang="fa" dir="rtl".
 * The <html> element is the authoritative direction for the whole app,
 * so flex layouts (including the sidebar shell) flip automatically in RTL.
 */
function useDocumentDirection() {
  useEffect(() => {
    const apply = (lng: string) => {
      const code = lng?.startsWith('fa') ? 'fa' : 'en'
      document.documentElement.lang = code
      document.documentElement.dir = getLanguageDirection(code)
    }
    apply(i18n.language)
    i18n.on('languageChanged', apply)
    return () => {
      i18n.off('languageChanged', apply)
    }
  }, [])
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false)

  useDocumentDirection()

  useEffect(() => {
    setMounted(true)
  }, [])

  // Avoid hydration mismatch by waiting for mount
  if (!mounted) {
    return <div style={{ visibility: 'hidden' }}>{children}</div>
  }

  return (
    <>
      <LanguageLoadingOverlay />
      {children}
    </>
  )
}
