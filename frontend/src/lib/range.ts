import { addDays, daysBetween, isDay, todayLocal } from './format'

export const PRESETS = ['24h', '7d', '30d', '90d', '1y', 'all', 'custom'] as const
export type RangePreset = (typeof PRESETS)[number]

/**
 * The global range lives in the URL: ?r=30d  or  ?r=custom&from=2026-09-01&to=2026-09-30.
 * `end` moves a preset window back in time (last day of the window, absent = today).
 */
export interface RangeSearch {
  r?: RangePreset
  from?: string
  to?: string
  end?: string
}

export interface ResolvedRange {
  preset: RangePreset
  from: string
  to: string
  days: number
  /** True when the window ends today (the "live" window); false after the arrows moved it back. */
  current: boolean
}

export interface RangeInput {
  preset: RangePreset
  from?: string
  to?: string
  end?: string
}

export const DEFAULT_PRESET = '7d' as const
export const MAX_CUSTOM_DAYS = 3660

export function parseRangeSearch(raw: Record<string, unknown>): RangeSearch {
  const out: RangeSearch = {}
  if (typeof raw.r === 'string' && (PRESETS as readonly string[]).includes(raw.r)) {
    out.r = raw.r as RangePreset
  }
  if (isDay(raw.from)) out.from = raw.from
  if (isDay(raw.to)) out.to = raw.to
  if (isDay(raw.end)) out.end = raw.end
  return out
}

const OFFSETS: Record<Exclude<RangePreset, 'custom' | 'all'>, number> = {
  '24h': 0,
  '7d': 6,
  '30d': 29,
  '90d': 89,
  '1y': 364,
}

/**
 * `firstDay` is the first day with data (from /data/bounds); it feeds the "all" preset.
 * Until it is known "all" shows the last year, so the page never waits on it.
 */
export function resolveRange(
  search: RangeSearch,
  today: string = todayLocal(),
  firstDay?: string | null,
): ResolvedRange {
  if (search.r === 'all') {
    const from = firstDay && firstDay <= today ? firstDay : addDays(today, -364)
    return { preset: 'all', from, to: today, days: daysBetween(from, today) + 1, current: true }
  }
  if (search.r === 'custom' && search.from && search.to && search.from <= search.to) {
    const days = daysBetween(search.from, search.to) + 1
    if (days <= MAX_CUSTOM_DAYS) {
      return { preset: 'custom', from: search.from, to: search.to, days, current: search.to >= today }
    }
  }
  const r = search.r
  const preset: keyof typeof OFFSETS =
    r !== undefined && r !== 'custom' ? r : DEFAULT_PRESET
  const to = search.end && search.end < today ? search.end : today
  return { preset, from: addDays(to, -OFFSETS[preset]), to, days: OFFSETS[preset] + 1, current: to === today }
}

/** The window one step back (-1) or forward (+1), as a URL-ready input; null when there is nowhere to go. */
export function shiftRange(range: ResolvedRange, direction: -1 | 1, today: string = todayLocal()): RangeInput | null {
  if (range.preset === 'all') return null
  if (direction > 0 && range.to >= today) return null
  let to = addDays(range.to, direction * range.days)
  if (to > today) to = today
  const from = addDays(to, -(range.days - 1))
  if (range.preset === 'custom') return { preset: 'custom', from, to }
  return { preset: range.preset, end: to === today ? undefined : to }
}

/** Keep the URL clean: the default preset is not written. */
export function toSearch(range: RangeInput): RangeSearch {
  if (range.preset === 'custom') return { r: 'custom', from: range.from, to: range.to }
  const end = range.end ? { end: range.end } : {}
  return range.preset === DEFAULT_PRESET ? end : { r: range.preset, ...end }
}
