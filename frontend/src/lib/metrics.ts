import type { Agg } from '../api/types'
import type { MessageKey } from '../i18n'
import { fmtNumber } from './format'
import type { palette } from './charts'

type PaletteKey = keyof ReturnType<typeof palette>

/**
 * The twelve metrics the dashboard shows (nothing else). `scale` converts the API unit into the
 * display unit (seconds -> hours, metres -> km) so charts and KPIs agree.
 */
export interface MetricDef {
  id: string
  /** Key of this metric in /report. */
  reportKey: string
  type: string
  field?: 'systolic' | 'diastolic'
  label: MessageKey
  unit: string
  scale: number
  digits: number
  agg: Agg
  kind: 'line' | 'bar'
  color: PaletteKey
  /** Draw the min-max band (heart rate). */
  band?: boolean
}

export const METRICS = {
  steps: { id: 'steps', reportKey: 'steps', type: 'Steps', label: 'm.steps', unit: '', scale: 1, digits: 0, agg: 'sum', kind: 'bar', color: 'glow' },
  heartRate: { id: 'heartRate', reportKey: 'heart_rate', type: 'HeartRate', label: 'm.heartRate', unit: 'bpm', scale: 1, digits: 0, agg: 'avg', kind: 'line', color: 'heart', band: true },
  restingHr: { id: 'restingHr', reportKey: 'resting_hr', type: 'RestingHeartRate', label: 'm.restingHr', unit: 'bpm', scale: 1, digits: 0, agg: 'avg', kind: 'line', color: 'heart' },
  hrv: { id: 'hrv', reportKey: 'hrv', type: 'HeartRateVariabilityRmssd', label: 'm.hrv', unit: 'ms', scale: 1, digits: 0, agg: 'avg', kind: 'line', color: 'vitals' },
  spo2: { id: 'spo2', reportKey: 'spo2', type: 'OxygenSaturation', label: 'm.spo2', unit: '%', scale: 1, digits: 1, agg: 'avg', kind: 'line', color: 'vitals' },
  sleep: { id: 'sleep', reportKey: 'sleep', type: 'SleepSession', label: 'm.sleep', unit: 'h', scale: 1 / 3600, digits: 1, agg: 'sum', kind: 'bar', color: 'sleep' },
  distance: { id: 'distance', reportKey: 'distance', type: 'Distance', label: 'm.distance', unit: 'km', scale: 1 / 1000, digits: 1, agg: 'sum', kind: 'bar', color: 'glow' },
  activeKcal: { id: 'activeKcal', reportKey: 'active_kcal', type: 'ActiveCaloriesBurned', label: 'm.activeKcal', unit: 'kcal', scale: 1, digits: 0, agg: 'sum', kind: 'bar', color: 'energy' },
  totalKcal: { id: 'totalKcal', reportKey: 'total_kcal', type: 'TotalCaloriesBurned', label: 'm.totalKcal', unit: 'kcal', scale: 1, digits: 0, agg: 'sum', kind: 'bar', color: 'energy' },
  weight: { id: 'weight', reportKey: 'weight', type: 'Weight', label: 'm.weight', unit: 'kg', scale: 1, digits: 1, agg: 'avg', kind: 'line', color: 'accent' },
  systolic: { id: 'systolic', reportKey: 'blood_pressure', type: 'BloodPressure', field: 'systolic', label: 'm.systolic', unit: 'mmHg', scale: 1, digits: 0, agg: 'avg', kind: 'line', color: 'heart' },
  diastolic: { id: 'diastolic', reportKey: 'blood_pressure', type: 'BloodPressure', field: 'diastolic', label: 'm.diastolic', unit: 'mmHg', scale: 1, digits: 0, agg: 'avg', kind: 'line', color: 'heart' },
} as const satisfies Record<string, MetricDef>

export function scaled(def: Pick<MetricDef, 'scale'>, v: number | null | undefined): number | null {
  return v === null || v === undefined ? null : v * def.scale
}

export function fmtMetric(def: Pick<MetricDef, 'scale' | 'digits'>, v: number | null | undefined, digits?: number): string {
  return fmtNumber(scaled(def, v), digits ?? def.digits)
}

/** "10.200" / "72 bpm": value with its unit when it has one. */
export function withUnit(def: Pick<MetricDef, 'unit'>, text: string): string {
  return def.unit ? `${text} ${def.unit}` : text
}
