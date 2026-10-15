import { addDays, daysBetween, isDay, todayLocal } from './format'

/** Report period, kept in the URL so a report can be reopened or shared: ?p=month&d=2026-09-01 */
export const PERIOD_KINDS = ['week', 'month', 'year', 'custom'] as const
export type PeriodKind = (typeof PERIOD_KINDS)[number]

export interface PeriodSearch {
  p?: PeriodKind
  /** Any day inside the period (week/month/year). */
  d?: string
  from?: string
  to?: string
}

export interface Period {
  kind: PeriodKind
  /** First and last calendar day of the period. */
  start: string
  end: string
  /** Last day with possible data: the period end, or today when the period is still running. */
  last: string
  days: number
  anchor: string
}

export function parsePeriodSearch(raw: Record<string, unknown>): PeriodSearch {
  const out: PeriodSearch = {}
  if (typeof raw.p === 'string' && (PERIOD_KINDS as readonly string[]).includes(raw.p)) out.p = raw.p as PeriodKind
  if (isDay(raw.d)) out.d = raw.d
  if (isDay(raw.from)) out.from = raw.from
  if (isDay(raw.to)) out.to = raw.to
  return out
}

/** Monday of the week containing `day` (ISO weeks, like the writer). */
export function weekStart(day: string): string {
  const dow = (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7 // Monday = 0
  return addDays(day, -dow)
}

export function monthStart(day: string): string {
  return `${day.slice(0, 7)}-01`
}

export function monthEnd(day: string): string {
  const [y, m] = day.split('-').map(Number) as [number, number]
  const next = m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, '0')}-01`
  return addDays(next, -1)
}

export function resolvePeriod(search: PeriodSearch, today: string = todayLocal()): Period {
  let kind = search.p ?? 'week'
  if (kind === 'custom' && !(search.from && search.to && search.from <= search.to)) kind = 'week'
  const anchor = search.d ?? today
  let start: string
  let end: string
  if (kind === 'custom') {
    start = search.from as string
    end = search.to as string
  } else if (kind === 'month') {
    start = monthStart(anchor)
    end = monthEnd(anchor)
  } else if (kind === 'year') {
    start = `${anchor.slice(0, 4)}-01-01`
    end = `${anchor.slice(0, 4)}-12-31`
  } else {
    start = weekStart(anchor)
    end = addDays(start, 6)
  }
  const last = end > today ? today : end
  return { kind, start, end, last, days: Math.max(daysBetween(start, last) + 1, 0), anchor }
}

/** The period right before/after, as a new anchor day. */
export function shiftAnchor(p: Period, direction: -1 | 1): string {
  if (p.kind === 'week') return addDays(p.start, 7 * direction)
  if (p.kind === 'month') return direction < 0 ? monthStart(addDays(p.start, -1)) : addDays(p.end, 1)
  if (p.kind === 'year') return `${Number(p.start.slice(0, 4)) + direction}-01-01`
  return p.anchor
}

export function canGoNext(p: Period, today: string = todayLocal()): boolean {
  return p.kind !== 'custom' && p.end < today
}
