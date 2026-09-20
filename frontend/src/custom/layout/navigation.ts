import type { LucideIcon } from 'lucide-react'
import {
  Book,
  Bot,
  FileText,
  Mic,
  Search,
  Settings,
  Shuffle,
  Wrench,
} from 'lucide-react'

export interface CustomNavigationItem {
  /** i18n key resolved with t() at render time; never a translated string. */
  key: string
  href: string
  icon: LucideIcon
  accentClass?: string
}

export interface CustomNavigationSection {
  /** i18n key for the section heading. */
  key: string
  items: CustomNavigationItem[]
}

/** Centralized downstream navigation. Mirrors upstream route semantics. */
export const customNavigation: CustomNavigationSection[] = [
  {
    key: 'navigation.collect',
    items: [
      { key: 'navigation.sources', href: '/sources', icon: FileText, accentClass: 'text-sage' },
    ],
  },
  {
    key: 'navigation.process',
    items: [
      { key: 'navigation.notebooks', href: '/notebooks', icon: Book, accentClass: 'text-teal' },
      { key: 'navigation.askAndSearch', href: '/search', icon: Search },
    ],
  },
  {
    key: 'navigation.create',
    items: [
      { key: 'navigation.podcasts', href: '/podcasts', icon: Mic, accentClass: 'text-mauve' },
    ],
  },
  {
    key: 'navigation.manage',
    items: [
      { key: 'navigation.models', href: '/settings/models', icon: Bot },
      { key: 'navigation.transformations', href: '/transformations', icon: Shuffle },
      { key: 'navigation.settings', href: '/settings', icon: Settings },
      { key: 'navigation.advanced', href: '/advanced', icon: Wrench },
    ],
  },
]

/**
 * The active item is the longest href that prefixes the current path.
 * Longest-wins keeps `/settings` from also highlighting on `/settings/models`.
 */
export function resolveActiveHref(pathname: string | null): string | undefined {
  return customNavigation
    .map((section) => section.items)
    .flat()
    .filter((item) => pathname === item.href || pathname?.startsWith(`${item.href}/`))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href
}
