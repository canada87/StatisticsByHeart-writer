import { addDays, daysBetween, isDay, todayLocal } from './format'

export const PRESETS = ['24h', '7d', '30d', '90d', '1y', 'custom'] as const
export type RangePreset = (typeof PRESETS)[number]

/** The global range lives in the URL: ?r=30d  or  ?r=custom&from=2026-09-01&to=2026-09-30 */
export interface RangeSearch {
  r?: RangePreset
  from?: string
  to?: string
}

export interface ResolvedRange {
  preset: RangePreset
  from: string
  to: string
  days: number
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
  return out
}

const OFFSETS: Record<Exclude<RangePreset, 'custom'>, number> = {
  '24h': 0,
  '7d': 6,
  '30d': 29,
  '90d': 89,
  '1y': 364,
}

export function resolveRange(search: RangeSearch, today: string = todayLocal()): ResolvedRange {
  if (search.r === 'custom' && search.from && search.to && search.from <= search.to) {
    const days = daysBetween(search.from, search.to) + 1
    if (days <= MAX_CUSTOM_DAYS) return { preset: 'custom', from: search.from, to: search.to, days }
  }
  const r = search.r
  const preset: Exclude<RangePreset, 'custom'> = r !== undefined && r !== 'custom' ? r : DEFAULT_PRESET
  return { preset, from: addDays(today, -OFFSETS[preset]), to: today, days: OFFSETS[preset] + 1 }
}

/** Keep the URL clean: the default preset is not written. */
export function toSearch(range: { preset: RangePreset; from?: string; to?: string }): RangeSearch {
  if (range.preset === 'custom') return { r: 'custom', from: range.from, to: range.to }
  return range.preset === DEFAULT_PRESET ? {} : { r: range.preset }
}
