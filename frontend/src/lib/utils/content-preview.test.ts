import { describe, expect, it } from 'vitest'
import { CONTENT_PREVIEW_ROWS, getContentPreview } from './content-preview'

function table(headers: string, rows: string[]): string {
  const columnCount = headers.split('|').length
  const sep = `|${' --- |'.repeat(columnCount)}`
  return [`| ${headers} |`, sep, ...rows.map((r) => `| ${r} |`)].join('\n')
}

describe('getContentPreview', () => {
  it('returns the text unchanged when there is no table', () => {
    const text = '# Title\n\nSome plain content.'
    const preview = getContentPreview(text)

    expect(preview.isPreview).toBe(false)
    expect(preview.text).toBe(text)
  })

  it('returns empty input unchanged', () => {
    expect(getContentPreview(null).isPreview).toBe(false)
    expect(getContentPreview('').text).toBe('')
  })

  it('returns small tables unchanged', () => {
    const text = table('a | b', ['1 | 2', '3 | 4'])
    const preview = getContentPreview(text)

    expect(preview.isPreview).toBe(false)
    expect(preview.text).toBe(text)
  })

  it('slices large tables to header plus five data rows', () => {
    const rows = Array.from({ length: 12 }, (_, i) => `${i} | row${i}`)
    const text = `# Sheet: Sheet1\n\n${table('code | name', rows)}`
    const preview = getContentPreview(text)

    expect(preview.isPreview).toBe(true)
    expect(preview.shownRows).toBe(CONTENT_PREVIEW_ROWS)
    expect(preview.totalRows).toBe(12)
    // Intro context preserved, only 5 data rows rendered
    expect(preview.text).toContain('# Sheet: Sheet1')
    expect(preview.text).toContain('row4')
    expect(preview.text).not.toContain('row5')
    expect(preview.text.split('\n').length).toBe(2 + 2 + CONTENT_PREVIEW_ROWS)
  })

  it('does not mutate the input', () => {
    const rows = Array.from({ length: 8 }, (_, i) => `${i} | row${i}`)
    const text = table('code | name', rows)
    getContentPreview(text)

    expect(text.split('\n').length).toBe(2 + 8)
  })

  it('counts multi-line rows as single logical rows', () => {
    // Real extraction output embeds newlines inside cells: continuation
    // lines do not start with `|`.
    const text = [
      '| code | notes |',
      '| --- | --- |',
      '| A1 | first line',
      'continued |',
      '| A2 | second |',
      '| A3 | third |',
      '| A4 | fourth |',
      '| A5 | fifth |',
      '| A6 | sixth |',
      '| A7 | seventh |',
    ].join('\n')
    const preview = getContentPreview(text)

    expect(preview.isPreview).toBe(true)
    expect(preview.totalRows).toBe(7)
    expect(preview.text).toContain('continued |')
    expect(preview.text).not.toContain('seventh')
  })
})
