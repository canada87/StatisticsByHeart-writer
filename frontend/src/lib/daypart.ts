import type { Bucket, DaypartPoint, NightInterval } from '../api/types'

type DaypartBucket = 'day' | 'week' | 'month'

/** Bucket the server will use for `auto` (mirror of choose_bucket for non-intraday ranges). */
export function autoDaypartBucket(days: number): DaypartBucket {
  return days <= 120 ? 'day' : days <= 800 ? 'week' : 'month'
}

/** The day/night split only exists for day, week and month buckets. */
export function daypartBucketFor(effective: Bucket, days: number): DaypartBucket | null {
  if (effective === 'day' || effective === 'week' || effective === 'month') return effective
  if (effective === 'auto') return days <= 1 ? null : autoDaypartBucket(days)
  return null
}

const STEP_MS: Partial<Record<Bucket, number>> = { '15min': 15 * 60_000, hour: 60 * 60_000 }

/** For each intraday point: does its time slot overlap a night? */
export function nightFlags(pointTimes: string[], bucket: Bucket, nights: NightInterval[]): boolean[] {
  const step = STEP_MS[bucket]
  if (!step) return pointTimes.map(() => false)
  const spans = nights.map((n) => [Date.parse(n.start), Date.parse(n.end)] as const)
  return pointTimes.map((t) => {
    const a = Date.parse(t)
    return spans.some(([s, e]) => a < e && a + step > s)
  })
}

/** Runs of consecutive night points as [first, last] indexes (inclusive). */
export function nightRuns(flags: boolean[]): [number, number][] {
  const runs: [number, number][] = []
  let start = -1
  flags.forEach((f, i) => {
    if (f && start < 0) start = i
    if (!f && start >= 0) {
      runs.push([start, i - 1])
      start = -1
    }
  })
  if (start >= 0) runs.push([start, flags.length - 1])
  return runs
}

/** Day and night values aligned to the main series' bucket starts. */
export function alignDaypart(
  keys: string[],
  points: DaypartPoint[],
): { day: (number | null)[]; night: (number | null)[]; dayN: number[]; nightN: number[] } {
  const byT = new Map(points.map((p) => [p.t, p]))
  return {
    day: keys.map((k) => byT.get(k)?.day ?? null),
    night: keys.map((k) => byT.get(k)?.night ?? null),
    dayN: keys.map((k) => byT.get(k)?.day_n ?? 0),
    nightN: keys.map((k) => byT.get(k)?.night_n ?? 0),
  }
}
