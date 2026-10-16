import { describe, expect, it } from 'vitest'
import type { NightInterval } from '../api/types'
import { alignDaypart, autoDaypartBucket, daypartBucketFor, nightFlags, nightRuns } from './daypart'

const night = (start: string, end: string): NightInterval => ({ date: '2026-10-14', start, end, source: 'sleep' })
const NIGHT = night('2026-10-13T21:30:00Z', '2026-10-14T04:30:00Z') // 23:30..06:30 local

describe('day / night helpers', () => {
  it('splits only day, week and month buckets', () => {
    expect(daypartBucketFor('day', 7)).toBe('day')
    expect(daypartBucketFor('week', 200)).toBe('week')
    expect(daypartBucketFor('hour', 7)).toBeNull()
    expect(daypartBucketFor('15min', 1)).toBeNull()
    expect(daypartBucketFor('auto', 1)).toBeNull()
    expect(daypartBucketFor('auto', 365)).toBe('week')
    expect(autoDaypartBucket(1000)).toBe('month')
  })
  it('flags the hourly slots that overlap a night', () => {
    const times = ['2026-10-14T00:00:00+02:00', '2026-10-14T05:00:00+02:00', '2026-10-14T06:00:00+02:00']
    expect(nightFlags(times, 'hour', [NIGHT])).toEqual([true, true, true])
    expect(nightFlags(['2026-10-14T08:00:00+02:00'], 'hour', [NIGHT])).toEqual([false])
    expect(nightFlags(['2026-10-14'], 'day', [NIGHT])).toEqual([false])
  })
  it('groups consecutive night points into runs', () => {
    expect(nightRuns([false, true, true, false, true])).toEqual([
      [1, 2],
      [4, 4],
    ])
    expect(nightRuns([])).toEqual([])
  })
  it('aligns the split to the bucket starts of the main series', () => {
    const a = alignDaypart(['a', 'b'], [{ t: 'b', day: 70, night: 55, day_n: 3, night_n: 2 }])
    expect(a.day).toEqual([null, 70])
    expect(a.night).toEqual([null, 55])
    expect(a.dayN).toEqual([0, 3])
  })
})
