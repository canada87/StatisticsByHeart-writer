import type {
  PointsRules,
  ReportMonthly,
  PointsSeriesResponse,
  PointsWeek,
  StorageResponse,
  DaypartResponse,
  ExerciseResponse,
  ExerciseRules,
  PeriodStats,
  ReportMetric,
  ReportResponse,
  SeriesResponse,
  SleepNightsResponse,
} from '../api/types'
import { series as baseSeries } from './fixtures'

const stats = (avg: number | null, extra: Partial<PeriodStats> = {}): PeriodStats => ({
  days: avg === null ? 0 : 7,
  total: null,
  avg,
  min: avg === null ? null : avg - 5,
  max: avg === null ? null : avg + 5,
  ...extra,
})

function metric(key: string, type: string, unit: string | null, kind: ReportMetric['kind'], over: Partial<ReportMetric> = {}): ReportMetric {
  const cur = kind === 'sum' ? stats(1000, { total: 7000, min: 800, max: 1200 }) : stats(70)
  return {
    key,
    type,
    unit,
    kind,
    days_with_data: 7,
    current: cur,
    previous: kind === 'sum' ? stats(950, { total: 6650 }) : stats(68),
    delta_abs: 350,
    delta_pct: 5.3,
    higher_is_better: true,
    best_day: { date: '2026-10-14', value: 1200 },
    worst_day: { date: '2026-10-11', value: 800 },
    first: 1,
    last: 2,
    spark: [1, 2, 3, 2, 3, 4, 3],
    spark_bucket: 'day',
    diastolic: null,
    sessions: null,
    ...over,
  }
}

const EMPTY = { days_with_data: 0, current: stats(null), previous: stats(null), delta_abs: null, delta_pct: null, best_day: null, worst_day: null, first: null, last: null, spark: [null, null] }

export function report(opts: { noBloodPressure?: boolean } = {}): ReportResponse {
  const bp = metric('blood_pressure', 'BloodPressure', 'mmHg', 'avg', {
    higher_is_better: null,
    diastolic: stats(78),
    ...(opts.noBloodPressure ? EMPTY : {}),
  })
  return {
    from: '2026-10-09',
    to: '2026-10-15',
    days: 7,
    previous_from: '2026-10-02',
    previous_to: '2026-10-08',
    generated_at: '2026-10-15T10:00:00Z',
    timezone: 'Europe/Rome',
    metrics: [
      metric('steps', 'Steps', 'count', 'sum'),
      metric('heart_rate', 'HeartRate', 'bpm', 'range', { higher_is_better: null, best_day: null, worst_day: null }),
      metric('resting_hr', 'RestingHeartRate', 'bpm', 'avg', { higher_is_better: false }),
      metric('sleep', 'SleepSession', 's', 'sum', { current: stats(25000, { total: 175000, min: 21000, max: 29000 }), previous: stats(24000, { total: 168000 }) }),
      metric('workouts', 'ExerciseSession', 's', 'sum', { sessions: 3, current: stats(2700, { total: 8100 }), previous: stats(2500, { total: 7500 }) }),
      metric('active_kcal', 'ActiveCaloriesBurned', 'kcal', 'sum'),
      metric('total_kcal', 'TotalCaloriesBurned', 'kcal', 'sum', { higher_is_better: null }),
      metric('distance', 'Distance', 'm', 'sum', { current: stats(7000, { total: 49000, min: 5000, max: 9000 }), previous: stats(6500, { total: 45500 }) }),
      metric('weight', 'Weight', 'kg', 'avg', { higher_is_better: null }),
      metric('spo2', 'OxygenSaturation', 'percent', 'avg'),
      metric('hrv', 'HeartRateVariabilityRmssd', 'ms', 'avg'),
      bp,
    ],
    sleep_regularity: {
      nights: 7,
      avg_asleep_s: 25000,
      avg_in_bed_s: 27000,
      bedtime_avg_min: 310,
      wake_avg_min: 400,
      bedtime_sd_min: 22,
      wake_sd_min: 18,
    },
    extra_metrics: [
      metric('hr_day', 'HeartRateDay', 'bpm', 'avg', { higher_is_better: null, current: stats(76), previous: stats(74) }),
      metric('hr_night', 'HeartRateNight', 'bpm', 'avg', { higher_is_better: null, current: stats(54), previous: stats(56) }),
      metric('heart_points', 'HeartPoints', 'points', 'sum', { current: stats(20, { total: 140, min: 0, max: 60 }), previous: stats(18, { total: 126 }) }),
    ],
    points: { total: 140, previous_total: 126, weekly_avg: 140, weeks_complete: 1, weeks_over_goal: 0, goal: 150, hr_configured: true },
    monthly: monthlyFixture('2026-10-09', '2026-10-15'),
    workouts: {
      count: 3,
      duration_s: 8100,
      avg_duration_s: 2700,
      per_week: 3,
      by_type: { RUNNING: 2, BIKING: 1 },
      by_type_detail: [
        { type: 'RUNNING', count: 2, duration_s: 4500 },
        { type: 'BIKING', count: 1, duration_s: 3600 },
      ],
      scope: 'real',
      excluded: 4,
    },
  }
}

/** Month-by-month fixture: one month, or the months a window crosses (the ends are partial). */
export function monthlyFixture(from: string, to: string): ReportMonthly {
  const first = new Date(`${from}T00:00:00Z`)
  const last = new Date(`${to}T00:00:00Z`)
  const months: ReportMonthly['months'] = []
  for (let c = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1)); c <= last; c = new Date(Date.UTC(c.getUTCFullYear(), c.getUTCMonth() + 1, 1))) {
    const end = new Date(Date.UTC(c.getUTCFullYear(), c.getUTCMonth() + 1, 0))
    const lo = c < first ? first : c
    const hi = end > last ? last : end
    const i = months.length
    months.push({
      month: c.toISOString().slice(0, 10),
      days: Math.round((hi.getTime() - lo.getTime()) / 86_400_000) + 1,
      partial: c < first || end > last,
      values: {
        heart_rate: 70 + i, hr_day: 76 + i, hr_night: 54 + i, resting_hr: 57 - i, hrv: 48 + i, spo2: 96.5, sleep: 25000 + i * 600,
        weight: 78.4 - i * 0.2, systolic: 118, diastolic: 77,
        steps: 280000 + i * 1000, distance: 210000, active_kcal: 8400, total_kcal: 58000, heart_points: 300 + i * 40,
        workouts: 11 - i, workouts_s: 30000 + i * 900,
      },
    })
  }
  const kinds: Record<string, 'avg' | 'sum'> = {
    heart_rate: 'avg', hr_day: 'avg', hr_night: 'avg', resting_hr: 'avg', hrv: 'avg', spo2: 'avg', sleep: 'avg', weight: 'avg', systolic: 'avg', diastolic: 'avg',
    steps: 'sum', distance: 'sum', active_kcal: 'sum', total_kcal: 'sum', heart_points: 'sum', workouts: 'sum', workouts_s: 'sum',
  }
  return { columns: Object.entries(kinds).map(([key, kind]) => ({ key, kind, unit: null })), months }
}

export function trendSeries(type: string, values: (number | null)[], over: Partial<SeriesResponse> = {}): SeriesResponse {
  const s = baseSeries(type, values)
  const prevAvg = 60
  return {
    ...s,
    previous_summary: { points: values.length, min: 50, max: 70, avg: prevAvg, total: prevAvg * values.length, first: 55, last: 61 },
    points: s.points.map((p, i) => ({
      ...p,
      lo: p.v === null ? null : p.v - 5,
      hi: p.v === null ? null : p.v + 5,
      ma: p.v === null ? null : p.v - 1,
      prev: i === 0 ? null : 60 + i,
    })),
    ...over,
  }
}

export const nights: SleepNightsResponse = {
  from: '2026-10-09',
  to: '2026-10-15',
  nights: [
    { date: '2026-10-14', asleep_s: 25200, in_bed_s: 27000, stages_s: { deep: 6000, light: 12000, rem: 5000, awake: 1800 }, start: '2026-10-13T21:10:00Z', end: '2026-10-14T04:40:00Z', bedtime_min: 310, wake_min: 400 },
    { date: '2026-10-15', asleep_s: 24000, in_bed_s: 26000, stages_s: { deep: 5000, light: 12500, rem: 5500, awake: 1500 }, start: '2026-10-14T21:30:00Z', end: '2026-10-15T04:50:00Z', bedtime_min: 330, wake_min: 410 },
  ],
  summary: { nights: 2, avg_asleep_s: 24600, avg_in_bed_s: 26500, bedtime_avg_min: 320, wake_avg_min: 405, bedtime_sd_min: 10, wake_sd_min: 5 },
  previous: { nights: 2, avg_asleep_s: 24000, avg_in_bed_s: 26000, bedtime_avg_min: 308, wake_avg_min: 400, bedtime_sd_min: 12, wake_sd_min: 6 },
}

export const exercise: ExerciseResponse = {
  from: '2026-10-09',
  to: '2026-10-15',
  scope: 'real',
  total_count: 3,
  real_count: 2,
  sessions: [
    { id: 1, type: 'RUNNING', title: 'Easy run', start: '2026-10-14T16:00:00Z', end: '2026-10-14T16:35:00Z', duration_s: 2100, kcal: 310, avg_hr: 148, source_package: 'synthetic.watch', has_route: true, hr_coverage: 0.95, has_hr: true, recording_method: 'active', started_by_user: true, auto_real: true, auto_rule: 'ok', min_duration_min: 15, override: null, is_real: true },
    { id: 2, type: 'WALKING', title: null, start: '2026-10-12T16:00:00Z', end: '2026-10-12T16:30:00Z', duration_s: 1800, kcal: null, avg_hr: null, source_package: 'synthetic.watch', has_route: false, hr_coverage: 0.1, has_hr: false, recording_method: 'automatic', started_by_user: false, auto_real: false, auto_rule: 'type', min_duration_min: 15, override: true, is_real: true },
  ],
  weekly: [
    { week_start: '2026-10-05', count: 1, duration_s: 1800, kcal: 0 },
    { week_start: '2026-10-12', count: 1, duration_s: 2100, kcal: 310 },
  ],
  summary: { count: 2, duration_s: 3900, avg_duration_s: 1950, kcal: 310, by_type: { RUNNING: 1, WALKING: 1 } },
  previous: { count: 1, duration_s: 3000, avg_duration_s: 3000, kcal: null, by_type: { WALKING: 1 } },
}

/** Day/night split for the 7 synthetic days 09..15 Oct (night is ~18 bpm lower). */
export function daypart(over: Partial<DaypartResponse> = {}): DaypartResponse {
  const days = [9, 10, 11, 12, 13, 14, 15]
  const dd = (n: number) => String(n).padStart(2, '0')
  return {
    from: '2026-10-09',
    to: '2026-10-15',
    bucket: 'day',
    timezone: 'Europe/Rome',
    fixed_window: '23:00-07:00',
    include_workouts: false,
    workouts: [],
    nights: days.map((d, i) => ({
      date: `2026-10-${dd(d)}`,
      start: `2026-10-${dd(d - 1)}T21:30:00Z`,
      end: `2026-10-${dd(d)}T04:30:00Z`,
      source: i === 3 ? ('fixed' as const) : ('sleep' as const),
    })),
    points: days.map((d, i) => ({
      t: `2026-10-${dd(d)}`,
      day: 74 + (i % 3),
      night: 55 + (i % 2),
      day_n: 200,
      night_n: 60,
    })),
    summary: {
      day: { avg: 75, days: 7, samples: 1400 },
      night: { avg: 55.5, days: 7, samples: 420 },
    },
    previous_from: '2026-10-02',
    previous_to: '2026-10-08',
    previous_summary: {
      day: { avg: 72, days: 7, samples: 1400 },
      night: { avg: 57, days: 6, samples: 360 },
    },
    ...over,
  }
}

export const exerciseRules: ExerciseRules = {
  rules: [
    { id: 'override', params: {} },
    { id: 'type', params: { types: ['WALKING'] } },
    { id: 'duration', params: { min_minutes: 15 } },
    { id: 'default', params: {} },
  ],
  daytime_hr: { excludes: 'real_workouts', recovery_minutes: 30 },
  signals: { hr_min_share: 0.5, user_started_methods: ['active', 'manual'], informative_only: true },
}

export const storage: StorageResponse = {
  database_bytes: 52_428_800,
  postgres_version: '16.4',
  tables: [
    { name: 'health_sample', total_bytes: 30_000_000, data_bytes: 22_000_000, index_bytes: 8_000_000, rows: 400_000, rows_exact: false },
    { name: 'health_record', total_bytes: 9_000_000, data_bytes: 6_000_000, index_bytes: 3_000_000, rows: 30_000, rows_exact: true },
    { name: 'daily_metric', total_bytes: 1_200_000, data_bytes: 900_000, index_bytes: 300_000, rows: 4_000, rows_exact: true },
    { name: 'admin_user', total_bytes: 16_384, data_bytes: 8_192, index_bytes: 8_192, rows: 1, rows_exact: true },
  ],
  records_live: 29_990,
  records_deleted: 10,
  first_data: '2026-01-01T06:00:00Z',
  last_data: '2026-10-15T10:00:00Z',
  last_ingest: '2026-10-15T10:05:00Z',
  growth: { window_days: 30, records: 3_000, samples: 40_000, bytes: 3_145_728, bytes_per_month: 3_145_728, bytes_per_year: 38_273_024, partial_history: false, estimated: true },
  disk: { total_bytes: 107_374_182_400, used_bytes: 32_212_254_720, free_bytes: 75_161_927_680, free_percent: 70 },
  limits: {
    items: [
      { id: 'retention', params: { forever: true } },
      { id: 'soft_delete', params: { samples_removed: true } },
      { id: 'session_purge', params: { minute: 17, session_ttl_hours: 168 } },
      { id: 'daily_recompute', params: { hour: 3, minute: 30 } },
      { id: 'ingest_batch', params: { max_records: 500 } },
      { id: 'ingest_body', params: { max_bytes: 33_554_432 } },
      { id: 'route_points', params: { max_points: 50_000 } },
      { id: 'query_days', params: { max_days: 3660 } },
      { id: 'intraday', params: { minutes_15_max_days: 3, hour_max_days: 31 } },
      { id: 'chart_points', params: { max_points: 1000 } },
    ],
  },
}

export const pointsRules: PointsRules = {
  heart_rate: { moderate_pct: 50, vigorous_pct: 70, hr_max: 184, hr_max_source: 'birth_year', configured: true, carry_max_minutes: 5 },
  cadence: { moderate_steps: 100, vigorous_steps: 130, max_record_minutes: 60 },
  points: { moderate: 1, vigorous: 2 },
  combine: 'max',
  met_used: false,
  weekly_goal: 150,
  daily_reference: 150 / 7,
  week_starts: 'monday',
  timezone: 'Europe/Rome',
}

export function pointsWeek(over: Partial<PointsWeek> = {}): PointsWeek {
  return {
    week_start: '2026-10-12',
    week_end: '2026-10-18',
    is_current: true,
    total: 96,
    goal: 150,
    remaining: 54,
    reached: false,
    days_left: 3,
    days: [],
    hr_configured: true,
    ...over,
  }
}

export function pointsSeries(over: Partial<PointsSeriesResponse> = {}): PointsSeriesResponse {
  return {
    from: '2026-09-21',
    to: '2026-10-15',
    bucket: 'week',
    weekly_goal: 150,
    daily_reference: 150 / 7,
    coarsened: false,
    timezone: 'Europe/Rome',
    hr_configured: true,
    points: [
      { t: '2026-09-21', v: 210, days: 7, complete: true },
      { t: '2026-09-28', v: 70, days: 7, complete: true },
      { t: '2026-10-05', v: 175, days: 7, complete: true },
      { t: '2026-10-12', v: 96, days: 4, complete: false },
    ],
    summary: { total: 551, days: 25, buckets_complete: 3, weeks_over_goal: 2, days_over_reference: null },
    previous_from: '2026-08-27',
    previous_to: '2026-09-20',
    previous_summary: { total: 400, days: 25 },
    ...over,
  }
}

/** Ten complete days (the last two partial) for the daily view. */
export function pointsSeriesDaily(over: Partial<PointsSeriesResponse> = {}): PointsSeriesResponse {
  const vals = [0, 21, 22, 50, 21, 30, 22, 5, 100, 12]
  return pointsSeries({
    bucket: 'day',
    from: '2026-10-06',
    to: '2026-10-15',
    points: vals.map((v, i) => ({
      t: `2026-10-${String(6 + i).padStart(2, '0')}`,
      v,
      days: 1,
      complete: i < 9,
    })),
    summary: { total: vals.reduce((a, b) => a + b, 0), days: 10, buckets_complete: 9, weeks_over_goal: null, days_over_reference: 5 },
    ...over,
  })
}
