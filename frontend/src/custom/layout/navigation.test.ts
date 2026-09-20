import { describe, it, expect } from 'vitest'
import { resolveActiveHref, customNavigation } from './navigation'

describe('resolveActiveHref', () => {
  it('matches exact routes', () => {
    expect(resolveActiveHref('/notebooks')).toBe('/notebooks')
    expect(resolveActiveHref('/sources')).toBe('/sources')
  })

  it('prefers the longest prefix so settings does not highlight on models', () => {
    expect(resolveActiveHref('/settings/models')).toBe('/settings/models')
  })

  it('matches nested notebook detail pages', () => {
    expect(resolveActiveHref('/notebooks/notebook:abc')).toBe('/notebooks')
  })

  it('returns undefined for unknown paths', () => {
    expect(resolveActiveHref('/unknown')).toBeUndefined()
    expect(resolveActiveHref(null)).toBeUndefined()
  })

  it('covers every upstream sidebar route', () => {
    const hrefs = customNavigation.map((section) => section.items.map((item) => item.href)).flat()
    expect(hrefs).toEqual([
      '/sources',
      '/notebooks',
      '/search',
      '/podcasts',
      '/settings/models',
      '/transformations',
      '/settings',
      '/advanced',
    ])
  })
})
