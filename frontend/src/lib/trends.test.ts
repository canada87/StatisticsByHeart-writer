import { describe, expect, it } from 'vitest'
import { toCsv } from './csv'
import { describeDelta, describeMinutes, describeTrend } from './delta'
import { METRICS, fmtMetric, scaled } from './metrics'
import { canGoNext, monthEnd, parsePeriodSearch, resolvePeriod, shiftAnchor, weekStart } from './period'
import { resolveRange } from './range'

const TODAY = '2026-10-15' // a Thursday

describe('report periods (URL state)', () => {
  it('weeks run Monday to Sunday and are clipped to today', () => {
    expect(weekStart('2026-10-15')).toBe('2026-10-12')
    expect(weekStart('2026-10-18')).toBe('2026-10-12') // Sunday belongs to the same week
    expect(weekStart('2026-10-19')).toBe('2026-10-19')
    const p = resolvePeriod({}, TODAY)
    expect(p).toMatchObject({ kind: 'week', start: '2026-10-12', end: '2026-10-18', last: TODAY, days: 4 })
  })
  it('months and years, including leap years and December', () => {
    expect(monthEnd('2026-02-10')).toBe('2026-02-28')
    expect(monthEnd('2028-02-10')).toBe('2028-02-29')
    expect(monthEnd('2026-12-05')).toBe('2026-12-31')
    expect(resolvePeriod({ p: 'month', d: '2026-09-17' }, TODAY)).toMatchObject({
      start: '2026-09-01',
      end: '2026-09-30',
      last: '2026-09-30',
      days: 30,
    })
    expect(resolvePeriod({ p: 'year', d: '2025-06-01' }, TODAY)).toMatchObject({ start: '2025-01-01', end: '2025-12-31', days: 365 })
  })
  it('custom needs a valid from/to, otherwise it falls back to the week', () => {
    expect(resolvePeriod({ p: 'custom', from: '2026-09-01', to: '2026-09-10' }, TODAY)).toMatchObject({ kind: 'custom', days: 10 })
    expect(resolvePeriod({ p: 'custom', from: '2026-09-10', to: '2026-09-01' }, TODAY).kind).toBe('week')
    expect(resolvePeriod({ p: 'custom' }, TODAY).kind).toBe('week')
  })
  it('previous/next steps by one period; cannot go past today', () => {
    const w = resolvePeriod({}, TODAY)
    expect(shiftAnchor(w, -1)).toBe('2026-10-05')
    const m = resolvePeriod({ p: 'month', d: '2026-03-31' }, TODAY)
    expect(shiftAnchor(m, -1)).toBe('2026-02-01')
    expect(shiftAnchor(m, 1)).toBe('2026-04-01')
    const y = resolvePeriod({ p: 'year', d: '2026-05-05' }, TODAY)
    expect(shiftAnchor(y, -1)).toBe('2025-01-01')
    expect(canGoNext(w, TODAY)).toBe(false) // the current week is still running
    expect(canGoNext(resolvePeriod({ d: '2026-10-05' }, TODAY), TODAY)).toBe(true)
    expect(canGoNext(resolvePeriod({ p: 'month', d: '2026-09-01' }, TODAY), TODAY)).toBe(true)
    expect(canGoNext(resolvePeriod({ p: 'month', d: '2026-10-01' }, TODAY), TODAY)).toBe(false)
    expect(canGoNext(resolvePeriod({ p: 'custom', from: '2026-01-01', to: '2026-01-31' }, TODAY), TODAY)).toBe(false)
  })
  it('sanitises URL input', () => {
    expect(parsePeriodSearch({ p: 'decade', d: 'yesterday', from: '2026-01-01' })).toEqual({ from: '2026-01-01' })
  })
})

describe('"Tutto" range', () => {
  it('starts at the first day with data', () => {
    expect(resolveRange({ r: 'all' }, TODAY, '2026-03-02')).toMatchObject({ preset: 'all', from: '2026-03-02', to: TODAY })
    expect(resolveRange({ r: 'all' }, TODAY, '2026-03-02').days).toBe(228)
  })
  it('falls back to a year while the bounds are unknown or nonsensical', () => {
    expect(resolveRange({ r: 'all' }, TODAY, null)).toMatchObject({ from: '2025-10-16', days: 365 })
    expect(resolveRange({ r: 'all' }, TODAY, '2030-01-01').days).toBe(365)
  })
})

describe('CSV', () => {
  it('quotes separators, quotes and newlines', () => {
    expect(toCsv(['a', 'b'], [['x,y', 'say "hi"'], ['line\nbreak', 1.5]])).toBe('a,b\r\n"x,y","say ""hi"""\r\n"line\nbreak",1.5\r\n')
  })
  it('keeps numbers numeric, empties null, and defuses spreadsheet formulas in text', () => {
    expect(toCsv(['n'], [[-5], [null], [undefined], [Number.NaN]])).toBe('n\r\n-5\r\n\r\n\r\n\r\n')
    expect(toCsv(['t'], [['=HYPERLINK("x")'], ['+1'], ['@sum'], ['ok']])).toContain("'=HYPERLINK")
    expect(toCsv(['t'], [['-cmd']])).toContain("'-cmd")
  })
})

describe('deltas are words and arrows, never only colour', () => {
  it('describes direction, size and a screen-reader sentence', () => {
    const up = describeDelta(110, 100)
    expect(up).toMatchObject({ direction: 'up', text: '+10% vs periodo prec.' })
    expect(up.sr).toContain('in aumento')
    const down = describeDelta(90, 100)
    expect(down.direction).toBe('down')
    expect(down.text).toContain('−10')
    expect(down.sr).toContain('in calo')
    expect(describeDelta(100.2, 100).direction).toBe('flat')
  })
  it('has no comparison without a usable previous value', () => {
    expect(describeDelta(5, null).direction).toBe('none')
    expect(describeDelta(5, 0).direction).toBe('none')
    expect(describeDelta(null, 5).direction).toBe('none')
  })
  it('clock-time deltas are in minutes, earlier/later', () => {
    expect(describeMinutes(320, 308)).toMatchObject({ direction: 'up', text: '+12 min vs periodo prec.' })
    expect(describeMinutes(300, 308).sr).toContain('più presto')
    expect(describeMinutes(300, 301).direction).toBe('flat')
    expect(describeMinutes(null, 301).direction).toBe('none')
  })
  it('trend compares the first and the last third', () => {
    expect(describeTrend([1, 1, 1, 2, 2, 2, 3, 3, 3])).toBe('up')
    expect(describeTrend([3, 3, 3, 2, 2, 2, 1, 1, 1])).toBe('down')
    expect(describeTrend([5, 5, 5, 5, 5, 5])).toBe('stable')
    expect(describeTrend([1, 2, 3])).toBeNull()
  })
})

describe('metric display units', () => {
  it('converts seconds to hours and metres to km, leaves the rest alone', () => {
    expect(scaled(METRICS.sleep, 25200)).toBe(7)
    expect(fmtMetric(METRICS.sleep, 27000)).toBe('7,5')
    expect(fmtMetric(METRICS.distance, 7550)).toBe('7,6')
    expect(fmtMetric(METRICS.steps, 10200)).toBe('10.200')
    expect(fmtMetric(METRICS.weight, null)).toBe('—')
  })
  it('covers exactly the twelve metrics of interest', () => {
    const types = new Set(Object.values(METRICS).map((m) => m.type))
    expect([...types].sort()).toEqual(
      [
        'ActiveCaloriesBurned',
        'BloodPressure',
        'Distance',
        'HeartRate',
        'HeartRateVariabilityRmssd',
        'OxygenSaturation',
        'RestingHeartRate',
        'SleepSession',
        'Steps',
        'TotalCaloriesBurned',
        'Weight',
      ].sort(),
    )
  })
})
