import { describe, expect, it } from 'vitest'
import { addDays, daysBetween, fmtDuration, fmtNumber, timeAgo, todayLocal } from './format'
import { parseRangeSearch, resolveRange, shiftRange, todayRange, toSearch } from './range'

const TODAY = '2026-10-15'

describe('range (URL state)', () => {
  it('defaults to 7 days ending today', () => {
    expect(resolveRange({}, TODAY)).toEqual({ preset: '7d', from: '2026-10-09', to: TODAY, days: 7, current: true })
  })
  it('resolves every preset', () => {
    expect(resolveRange({ r: '24h' }, TODAY)).toMatchObject({ from: TODAY, to: TODAY, days: 1 })
    expect(resolveRange({ r: '30d' }, TODAY).days).toBe(30)
    expect(resolveRange({ r: '90d' }, TODAY).days).toBe(90)
    expect(resolveRange({ r: '1y' }, TODAY).days).toBe(365)
  })
  it('accepts a valid custom range and rejects invalid ones', () => {
    expect(resolveRange({ r: 'custom', from: '2026-09-01', to: '2026-09-30' }, TODAY)).toEqual({
      preset: 'custom',
      from: '2026-09-01',
      to: '2026-09-30',
      days: 30,
      current: false,
    })
    expect(resolveRange({ r: 'custom', from: '2026-09-30', to: '2026-09-01' }, TODAY).preset).toBe('7d')
    expect(resolveRange({ r: 'custom' }, TODAY).preset).toBe('7d')
    expect(resolveRange({ r: 'custom', from: '2000-01-01', to: '2026-10-01' }, TODAY).preset).toBe('7d')
  })
  it('sanitises untrusted search params', () => {
    expect(parseRangeSearch({ r: 'bogus', from: 'nope', to: '2026-01-02' })).toEqual({ to: '2026-01-02' })
  })
  it('keeps the URL clean for the default', () => {
    expect(toSearch({ preset: '7d' })).toEqual({})
    expect(toSearch({ preset: '30d' })).toEqual({ r: '30d' })
    expect(toSearch({ preset: 'custom', from: 'a', to: 'b' })).toEqual({ r: 'custom', from: 'a', to: 'b' })
  })
})

describe('range shifting (arrows)', () => {
  it('resolves a preset that ends in the past (?end=)', () => {
    expect(resolveRange({ r: '7d', end: '2026-10-10' }, TODAY)).toEqual({
      preset: '7d',
      from: '2026-10-04',
      to: '2026-10-10',
      days: 7,
      current: false,
    })
    expect(resolveRange({ r: '24h', end: '2026-10-01' }, TODAY)).toMatchObject({ from: '2026-10-01', to: '2026-10-01' })
  })
  it('ignores an end in the future or today', () => {
    expect(resolveRange({ r: '7d', end: '2027-01-01' }, TODAY).to).toBe(TODAY)
    expect(resolveRange({ r: '7d', end: TODAY }, TODAY).current).toBe(true)
  })
  it('moves a preset by its own length and never past today', () => {
    const now = resolveRange({ r: '7d' }, TODAY)
    expect(shiftRange(now, 1, TODAY)).toBeNull()
    expect(shiftRange(now, -1, TODAY)).toEqual({ preset: '7d', end: '2026-10-08' })
    const back = resolveRange({ r: '7d', end: '2026-10-08' }, TODAY)
    expect(shiftRange(back, 1, TODAY)).toEqual({ preset: '7d', end: undefined }) // lands on today
    const far = resolveRange({ r: '30d', end: '2026-10-01' }, TODAY)
    expect(shiftRange(far, 1, TODAY)).toEqual({ preset: '30d', end: undefined }) // clamped to today
    expect(shiftRange(resolveRange({ r: '24h' }, TODAY), -1, TODAY)).toEqual({ preset: '24h', end: '2026-10-14' })
  })
  it('moves a custom range by its duration', () => {
    const c = resolveRange({ r: 'custom', from: '2026-09-01', to: '2026-09-30' }, TODAY)
    expect(shiftRange(c, -1, TODAY)).toEqual({ preset: 'custom', from: '2026-08-02', to: '2026-08-31' })
    expect(shiftRange(c, 1, TODAY)).toEqual({ preset: 'custom', from: '2026-09-16', to: TODAY }) // clamped at today, same length
  })
  it('"Oggi" drops the end and only exists when the window is in the past', () => {
    expect(todayRange(resolveRange({ r: '7d' }, TODAY), TODAY)).toBeNull()
    expect(todayRange(resolveRange({ r: '7d', end: '2026-10-10' }, TODAY), TODAY)).toEqual({ preset: '7d' })
    expect(toSearch(todayRange(resolveRange({ r: '30d', end: '2026-09-01' }, TODAY), TODAY) as never)).toEqual({ r: '30d' })
    const custom = resolveRange({ r: 'custom', from: '2026-09-01', to: '2026-09-30' }, TODAY)
    expect(todayRange(custom, TODAY)).toEqual({ preset: 'custom', from: '2026-09-16', to: TODAY })
    expect(todayRange(resolveRange({ r: 'all' }, TODAY, '2025-01-01'), TODAY)).toBeNull()
  })
  it('has no arrows for "all"', () => {
    expect(shiftRange(resolveRange({ r: 'all' }, TODAY, '2025-01-01'), -1, TODAY)).toBeNull()
  })
  it('writes end only when needed', () => {
    expect(toSearch({ preset: '7d', end: '2026-10-08' })).toEqual({ end: '2026-10-08' })
    expect(toSearch({ preset: '30d', end: '2026-10-08' })).toEqual({ r: '30d', end: '2026-10-08' })
    expect(parseRangeSearch({ end: '2026-10-08' })).toEqual({ end: '2026-10-08' })
  })
})

describe('format', () => {
  it('uses Italian number formatting and dashes for missing values', () => {
    expect(fmtNumber(10200)).toBe('10.200')
    expect(fmtNumber(9170.14, 1)).toBe('9170,1')
    expect(fmtNumber(null)).toBe('—')
  })
  it('formats durations', () => {
    expect(fmtDuration(27120)).toBe('7 h 32 min')
    expect(fmtDuration(2700)).toBe('45 min')
    expect(fmtDuration(7200)).toBe('2 h')
  })
  it('does date arithmetic on calendar days', () => {
    expect(addDays('2026-10-25', 1)).toBe('2026-10-26')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
    expect(daysBetween('2026-10-24', '2026-10-26')).toBe(2)
  })
  it('computes "today" in Europe/Rome, not UTC', () => {
    expect(todayLocal(new Date('2026-10-14T22:30:00Z'))).toBe('2026-10-15')
  })
  it('says how long ago', () => {
    const now = Date.parse('2026-10-15T12:00:00Z')
    expect(timeAgo('2026-10-15T11:59:30Z', now)).toBe('adesso')
    expect(timeAgo('2026-10-15T11:00:00Z', now)).toBe('1 h fa')
    expect(timeAgo('2026-10-15T07:00:00Z', now)).toBe('5 h fa')
    expect(timeAgo(null, now)).toBe('mai')
  })
})
