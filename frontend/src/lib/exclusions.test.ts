import { describe, expect, it } from 'vitest'
import { MAX_MEASURE_DAYS, bucketWindow, clampWindow, formatMeasure, isExcludable } from './exclusions'

const base = { type: 'Weight', value: 32, value2: null, unit: 'kg', label: null }

describe('exclusion helpers', () => {
  it('only point measures and sessions are excludable', () => {
    for (const t of ['Weight', 'BloodPressure', 'OxygenSaturation', 'RestingHeartRate', 'HeartRateVariabilityRmssd', 'SleepSession', 'ExerciseSession']) {
      expect(isExcludable(t)).toBe(true)
    }
    for (const t of ['Steps', 'HeartRate', 'Distance', 'ActiveCaloriesBurned', 'TotalCaloriesBurned', 'HeartPoints']) {
      expect(isExcludable(t)).toBe(false)
    }
  })

  it('writes the value the way the dashboard does', () => {
    expect(formatMeasure(base)).toBe('32 kg')
    expect(formatMeasure({ ...base, value: 71.4 })).toBe('71,4 kg')
    expect(formatMeasure({ ...base, type: 'BloodPressure', value: 190, value2: 120, unit: 'mmHg' })).toBe('190/120 mmHg')
    expect(formatMeasure({ ...base, type: 'OxygenSaturation', value: 94.4, unit: 'percent' })).toBe('94,4 %')
    expect(formatMeasure({ ...base, type: 'RestingHeartRate', value: 56, unit: 'bpm' })).toBe('56 bpm')
    expect(formatMeasure({ ...base, type: 'SleepSession', value: 27000, unit: 's' })).toBe('7 h 30 min')
    expect(formatMeasure({ ...base, type: 'ExerciseSession', value: 2100, unit: 's', label: 'Easy run' })).toBe('Easy run · 35 min')
    expect(formatMeasure({ ...base, value: null })).toBe('—')
  })

  it('a chart point stands for a day, a Monday-Sunday week or a month, clipped to the chart', () => {
    const range = { from: '2026-10-01', to: '2026-10-31' }
    expect(bucketWindow('2026-10-14', 'day', range)).toEqual({ from: '2026-10-14', to: '2026-10-14' })
    expect(bucketWindow('2026-10-12', 'week', range)).toEqual({ from: '2026-10-12', to: '2026-10-18' })
    expect(bucketWindow('2026-10-26', 'week', range)).toEqual({ from: '2026-10-26', to: '2026-10-31' }) // clipped
    expect(bucketWindow('2026-09-28', 'week', range)).toEqual({ from: '2026-10-01', to: '2026-10-04' }) // clipped at the start
    expect(bucketWindow('2026-09-01', 'month', { from: '2026-08-15', to: '2026-12-31' })).toEqual({ from: '2026-09-01', to: '2026-09-30' })
    expect(bucketWindow('2026-12-01', 'month', { from: '2026-01-01', to: '2026-12-31' })).toEqual({ from: '2026-12-01', to: '2026-12-31' })
    expect(bucketWindow('2028-02-01', 'month', { from: '2028-01-01', to: '2028-12-31' }).to).toBe('2028-02-29')
  })

  it('the server lists at most MAX_MEASURE_DAYS days: the most recent ones are kept', () => {
    const w = clampWindow({ from: '2020-01-01', to: '2026-10-15' })
    expect(w.to).toBe('2026-10-15')
    expect((Date.parse(w.to) - Date.parse(w.from)) / 86_400_000 + 1).toBe(MAX_MEASURE_DAYS)
    expect(clampWindow({ from: '2026-10-01', to: '2026-10-15' })).toEqual({ from: '2026-10-01', to: '2026-10-15' })
  })
})
