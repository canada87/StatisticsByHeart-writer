import type { MessageKey } from '../i18n'

/** Name of the server-side preference that holds the choice (shared by every device). */
export const REPORT_SECTIONS_KEY = 'report-sections'

export interface SectionDef {
  id: string
  label: MessageKey
  group: 'sections' | 'metrics'
}

/**
 * What the report can show. `sections` are blocks of the page, `metrics` are measures that appear in
 * several places at once (summary row, month columns, chart): switching one off removes it everywhere.
 * A section that is not listed here (an older page reading a newer saved choice) is simply ignored,
 * and a new one is ON until someone turns it off.
 */
export const SECTION_DEFS: readonly SectionDef[] = [
  { id: 'summary', label: 'report.sel.summary', group: 'sections' },
  { id: 'monthly', label: 'report.sel.monthly', group: 'sections' },
  { id: 'workouts', label: 'report.sel.workouts', group: 'sections' },
  { id: 'charts', label: 'report.sel.charts', group: 'sections' },
  { id: 'steps', label: 'm.steps', group: 'metrics' },
  { id: 'distance', label: 'm.distance', group: 'metrics' },
  { id: 'calories', label: 'report.sel.calories', group: 'metrics' },
  { id: 'hr', label: 'm.heartRate', group: 'metrics' },
  { id: 'hr_split', label: 'report.sel.hrSplit', group: 'metrics' },
  { id: 'resting_hr', label: 'm.restingHr', group: 'metrics' },
  { id: 'hrv', label: 'm.hrv', group: 'metrics' },
  { id: 'spo2', label: 'm.spo2', group: 'metrics' },
  { id: 'sleep', label: 'm.sleep', group: 'metrics' },
  { id: 'weight', label: 'm.weight', group: 'metrics' },
  { id: 'bp', label: 'm.bloodPressure', group: 'metrics' },
  { id: 'points', label: 'm.heartPoints', group: 'metrics' },
]

/** Row of the summary table -> the choice that controls it (workouts is a section). */
export const ROW_GROUP: Record<string, string> = {
  steps: 'steps',
  distance: 'distance',
  active_kcal: 'calories',
  total_kcal: 'calories',
  heart_rate: 'hr',
  hr_day: 'hr_split',
  hr_night: 'hr_split',
  resting_hr: 'resting_hr',
  hrv: 'hrv',
  spo2: 'spo2',
  sleep: 'sleep',
  workouts: 'workouts',
  weight: 'weight',
  blood_pressure: 'bp',
  heart_points: 'points',
}

/** Column of the month-by-month tables -> the choice that controls it. */
export const COLUMN_GROUP: Record<string, string> = {
  steps: 'steps',
  distance: 'distance',
  active_kcal: 'calories',
  total_kcal: 'calories',
  heart_rate: 'hr',
  hr_day: 'hr_split',
  hr_night: 'hr_split',
  resting_hr: 'resting_hr',
  hrv: 'hrv',
  spo2: 'spo2',
  sleep: 'sleep',
  sleep_nights: 'sleep',
  weight: 'weight',
  systolic: 'bp',
  diastolic: 'bp',
  heart_points: 'points',
  workouts: 'workouts',
  workouts_s: 'workouts',
}

export type Selection = Record<string, boolean>

/** Keep only boolean entries of whatever the server returned (null, a string, a list... -> nothing). */
export function normalizeSelection(raw: unknown): Selection {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return {}
  const out: Selection = {}
  for (const [k, v] of Object.entries(raw)) if (typeof v === 'boolean') out[k] = v
  return out
}

export type IsOn = (id: string) => boolean

export const selectionIsOn =
  (sel: Selection): IsOn =>
  (id) =>
    sel[id] !== false

/** Everything on: what the page uses before anything is saved. */
export const allOn: IsOn = () => true
