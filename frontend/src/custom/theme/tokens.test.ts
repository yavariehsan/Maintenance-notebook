import fs from 'fs'
import path from 'path'
import { describe, it, expect } from 'vitest'

const tokensCss = fs.readFileSync(
  path.resolve(__dirname, 'tokens.css'),
  'utf-8',
)

describe('Locale typography tokens', () => {
  it('scopes the Persian-capable font to fa without touching English', () => {
    // Vazirmatn stack applies only under html[lang="fa"].
    expect(tokensCss).toContain('html[lang="fa"] body')
    expect(tokensCss).toContain('var(--font-vazirmatn)')
    expect(tokensCss).toContain('html[lang="fa"] .font-display')
  })

  it('does not set a global body font that would override English', () => {
    const lines = tokensCss.split('\n')
    const globalBodyRules = lines.filter(
      (line) =>
        line.trim().startsWith('body {') ||
        line.trim().startsWith('body{'),
    )
    expect(globalBodyRules).toEqual([])
  })
})
