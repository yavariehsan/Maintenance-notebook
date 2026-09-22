/**
 * Lightweight Content-tab preview for large tabular sources.
 *
 * Large Excel-extracted sources arrive as one giant markdown table (hundreds
 * of rows x dozens of columns). Rendering the whole table through the
 * markdown pipeline builds tens of thousands of DOM nodes just for a visual
 * preview. This helper slices the FIRST markdown table down to its header +
 * separator + first 5 data rows. The stored/processed source is never
 * touched — slicing is render-only, and the full text stays available to the
 * embedding/retrieval pipeline.
 */

export const CONTENT_PREVIEW_ROWS = 5

export interface ContentPreview {
  /** Markdown to render in the Content tab. */
  text: string
  /** True when `text` is a truncated preview of a larger table. */
  isPreview: boolean
  /** Data rows shown (5 max). */
  shownRows: number
  /** Total data rows in the first table. */
  totalRows: number
}

function isTableRow(line: string): boolean {
  return line.trim().startsWith('|')
}

function isBlank(line: string): boolean {
  return line.trim().length === 0
}

function isSeparatorRow(line: string): boolean {
  const cells = line.trim().split('|').slice(1, -1)
  return (
    cells.length > 0 &&
    cells.every((cell) => /^[\s:-]+$/.test(cell) && cell.includes('-'))
  )
}

export function getContentPreview(fullText: string | null | undefined): ContentPreview {
  const empty: ContentPreview = { text: fullText ?? '', isPreview: false, shownRows: 0, totalRows: 0 }
  if (!fullText) return empty

  const lines = fullText.split('\n')
  // Locate the first markdown table: header row immediately followed by a
  // separator row (| --- | --- |).
  let headerIndex = -1
  for (let i = 0; i + 1 < lines.length; i++) {
    if (isTableRow(lines[i]) && isSeparatorRow(lines[i + 1])) {
      headerIndex = i
      break
    }
  }
  if (headerIndex === -1) return empty

  // Collect logical data rows. Real extraction output contains multi-line
  // cells: a logical row starts with a `|` line and absorbs following
  // non-blank continuation lines. A blank line ends the table.
  const logicalRows: string[][] = []
  let current: string[] | null = null
  const flush = () => {
    if (current) {
      logicalRows.push(current)
      current = null
    }
  }
  for (let i = headerIndex + 2; i < lines.length; i++) {
    const line = lines[i]
    if (isBlank(line)) {
      break
    }
    if (isTableRow(line)) {
      flush()
      current = [line]
    } else if (current) {
      current.push(line)
    } else {
      // Non-table content right after the separator: not a data table.
      break
    }
  }
  flush()
  const totalRows = logicalRows.length
  if (totalRows <= CONTENT_PREVIEW_ROWS) return empty

  const previewLines = [
    ...lines.slice(0, headerIndex + 2),
    ...logicalRows.slice(0, CONTENT_PREVIEW_ROWS).flat(),
  ]
  return {
    text: previewLines.join('\n'),
    isPreview: true,
    shownRows: CONTENT_PREVIEW_ROWS,
    totalRows,
  }
}
