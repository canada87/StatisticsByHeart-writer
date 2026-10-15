export type Cell = string | number | null | undefined

/** A text cell starting with = + - @ would be run as a formula by spreadsheets: neutralise it. */
function escape(cell: Cell): string {
  if (cell === null || cell === undefined) return ''
  if (typeof cell === 'number') return Number.isFinite(cell) ? String(cell) : ''
  const safe = /^[=+\-@\t\r]/.test(cell) ? `'${cell}` : cell
  return /[",\n\r]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe
}

/** RFC 4180 CSV: comma-separated, dot decimals, CRLF line ends. */
export function toCsv(columns: string[], rows: Cell[][]): string {
  return [columns, ...rows].map((r) => r.map(escape).join(',')).join('\r\n') + '\r\n'
}

/** Saves a CSV (with a UTF-8 BOM so Excel reads accents correctly). */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob(['﻿', csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function csvName(...parts: string[]): string {
  return `${parts.join('_').replace(/[^a-zA-Z0-9_.-]+/g, '-')}.csv`
}
