import type { MeasureItem } from '../api/types'
import { type MessageKey, t } from '../i18n'
import { addDays, fmtDuration, fmtNumber } from './format'

/** Point measures and sessions only: never whole days, never cumulative totals (ADR 0011). */
export const EXCLUDABLE_TYPES = [
  'Weight',
  'BloodPressure',
  'OxygenSaturation',
  'RestingHeartRate',
  'HeartRateVariabilityRmssd',
  'SleepSession',
  'ExerciseSession',
] as const

export const isExcludable = (type: string): boolean => (EXCLUDABLE_TYPES as readonly string[]).includes(type)

/** The server lists at most this many days at once. */
export const MAX_MEASURE_DAYS = 400

const TYPE_LABEL: Record<string, MessageKey> = {
  Weight: 'm.weight',
  BloodPressure: 'm.bloodPressure',
  OxygenSaturation: 'm.spo2',
  RestingHeartRate: 'm.restingHr',
  HeartRateVariabilityRmssd: 'm.hrv',
  SleepSession: 'm.sleep',
  ExerciseSession: 'm.workouts',
}

export function measureTypeLabel(type: string): string {
  const key = TYPE_LABEL[type]
  return key ? t(key) : type
}

const UNIT_TEXT: Record<string, string> = { percent: '%', kg: 'kg', bpm: 'bpm', ms: 'ms', mmHg: 'mmHg' }

/** "32 kg", "190/120 mmHg", "7 h 30 min", "Easy run · 35 min": the value as the dashboard writes it. */
export function formatMeasure(m: Pick<MeasureItem, 'type' | 'value' | 'value2' | 'unit' | 'label'>): string {
  if (m.value === null) return '—'
  if (m.type === 'SleepSession') return fmtDuration(m.value)
  if (m.type === 'ExerciseSession') return `${m.label ? `${m.label} · ` : ''}${fmtDuration(m.value)}`
  if (m.type === 'BloodPressure') {
    return `${fmtNumber(m.value, 0)}/${fmtNumber(m.value2, 0)} mmHg`
  }
  const unit = m.unit ? (UNIT_TEXT[m.unit] ?? m.unit) : ''
  return `${fmtNumber(m.value, m.type === 'Weight' || m.type === 'OxygenSaturation' ? 1 : 0)}${unit ? ` ${unit}` : ''}`
}

function lastDayOfMonth(day: string): string {
  const [y, m] = day.split('-').map(Number) as [number, number]
  return addDays(m === 12 ? `${y + 1}-01-01` : `${y}-${String(m + 1).padStart(2, '0')}-01`, -1)
}

/** The days a chart point aggregates (a day, a Monday-Sunday week, a month), clipped to the chart range. */
export function bucketWindow(
  t0: string,
  bucket: string,
  range: { from: string; to: string },
): { from: string; to: string } {
  const day = t0.slice(0, 10)
  let to = day
  if (bucket === 'week') to = addDays(day, 6)
  else if (bucket === 'month') to = lastDayOfMonth(day)
  const clipped = { from: day < range.from ? range.from : day, to: to > range.to ? range.to : to }
  return clipped.from > clipped.to ? { from: day, to: day } : clipped
}

/** The last MAX_MEASURE_DAYS days of a range (the server caps what it lists). */
export function clampWindow(w: { from: string; to: string }): { from: string; to: string } {
  const earliest = addDays(w.to, -(MAX_MEASURE_DAYS - 1))
  return { from: w.from < earliest ? earliest : w.from, to: w.to }
}
