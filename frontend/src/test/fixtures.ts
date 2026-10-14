import type {
  InventoryResponse,
  MetricValue,
  ReconciliationResponse,
  SeriesResponse,
  SyncStatusResponse,
  TodaySummary,
} from '../api/types'

const mv = (value: number | null, unit: string | null, extra: Partial<MetricValue> = {}): MetricValue => ({
  value,
  unit,
  date: value === null ? null : '2026-10-15',
  source: value === null ? null : 'hc_official',
  official: value,
  computed: value,
  ...extra,
})

export const summary: TodaySummary = {
  date: '2026-10-15',
  timezone: 'Europe/Rome',
  generated_at: '2026-10-15T10:00:00Z',
  steps: mv(10200, 'count'),
  distance_m: mv(7550, 'm'),
  active_kcal: mv(294, 'kcal', { source: 'computed', official: null }),
  total_kcal: mv(1974, 'kcal'),
  heart: {
    current: { time: new Date().toISOString(), value: 60 },
    resting: mv(56, 'bpm'),
    avg: 71,
    min: 45,
    max: 115,
    samples: 288,
  },
  sleep: {
    date: '2026-10-15',
    asleep_s: 6 * 3600 + 34 * 60,
    official_asleep_s: null,
    computed_asleep_s: 6 * 3600 + 34 * 60,
    in_bed_s: 24000,
    stages_s: { deep: 6660, light: 12540, rem: 4440 },
    start: '2026-10-14T21:52:00Z',
    end: '2026-10-15T04:26:00Z',
    sessions: 1,
  },
  spo2: mv(94.4, 'percent'),
  hrv: mv(34, 'ms'),
  activities: [
    {
      id: 1,
      type: 'WALKING',
      title: null,
      start: '2026-10-13T16:18:00Z',
      end: '2026-10-13T16:48:00Z',
      duration_s: 1800,
      source_package: 'synthetic.watch',
      has_route: true,
    },
  ],
  last_sync_at: new Date().toISOString(),
}

export const emptySummary: TodaySummary = {
  ...summary,
  steps: mv(null, 'count'),
  distance_m: mv(null, 'm'),
  active_kcal: mv(null, 'kcal'),
  total_kcal: mv(null, 'kcal'),
  heart: { current: null, resting: mv(null, 'bpm'), avg: null, min: null, max: null, samples: 0 },
  sleep: null,
  spo2: mv(null, 'percent'),
  hrv: mv(null, 'ms'),
  activities: [],
  last_sync_at: null,
}

export function series(type: string, values: (number | null)[]): SeriesResponse {
  const pts = values.map((v, i) => ({
    t: `2026-10-${String(9 + i).padStart(2, '0')}`,
    v,
    n: v === null ? null : 10,
  }))
  const nums = values.filter((v): v is number => v !== null)
  return {
    type,
    unit: type === 'Steps' ? 'count' : 'bpm',
    bucket: 'day',
    agg: type === 'Steps' ? 'sum' : 'avg',
    from: '2026-10-09',
    to: '2026-10-15',
    timezone: 'Europe/Rome',
    source: 'auto',
    source_counts: { hc_official: nums.length },
    points: pts,
    summary: {
      points: nums.length,
      min: nums.length ? Math.min(...nums) : null,
      max: nums.length ? Math.max(...nums) : null,
      avg: nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : null,
      total: nums.length ? nums.reduce((a, b) => a + b, 0) : null,
      first: nums[0] ?? null,
      last: nums[nums.length - 1] ?? null,
    },
  }
}

export const syncStatus: SyncStatusResponse = {
  generated_at: '2026-10-15T10:00:00Z',
  last_success_at: new Date().toISOString(),
  last_activity_at: new Date().toISOString(),
  devices: [
    {
      id: 'd1d1d1d1-0000-0000-0000-000000000000',
      name: 'Xiaomi test',
      model: null,
      app_version: '0.1.0',
      first_seen_at: '2026-10-01T00:00:00Z',
      last_seen_at: new Date().toISOString(),
    },
  ],
  runs: [
    {
      sync_id: 's1',
      device_id: 'd1d1d1d1-0000-0000-0000-000000000000',
      device_name: 'Xiaomi test',
      mode: 'backfill',
      status: 'partial',
      started_at: '2026-10-15T08:00:00Z',
      finished_at: '2026-10-15T08:00:05Z',
      duration_s: 5,
      last_activity_at: '2026-10-15T08:00:05Z',
      received: 1000,
      inserted: 990,
      updated: 0,
      unchanged: 0,
      rejected: 10,
      deletions: 0,
      aggregates: 14,
      reported_counts: { records_sent: 1000 },
      rejections: [{ type: 'Steps', reason: 'invalid_record', count: 10, detail: 'value: out of range' }],
      errors: [{ code: 'type_read_failed', type: 'Power', count: 1 }],
    },
  ],
}

export const inventory: InventoryResponse = {
  generated_at: '2026-10-15T10:00:00Z',
  records: 120,
  deleted: 2,
  samples: 500,
  types: [
    {
      type: 'Steps',
      unit: 'count',
      shape: 'interval',
      records: 100,
      deleted: 2,
      samples: 0,
      first: '2026-10-01T00:00:00Z',
      last: '2026-10-15T00:00:00Z',
      official_days: 14,
      computed_days: 15,
      sources: [
        { package: 'synthetic.phone', records: 60, first: null, last: null },
        { package: 'synthetic.watch', records: 40, first: null, last: null },
      ],
    },
  ],
  sources: [
    {
      package: 'synthetic.phone',
      records: 60,
      types: ['Steps'],
      first: '2026-10-01T00:00:00Z',
      last: '2026-10-15T00:00:00Z',
    },
    { package: 'synthetic.watch', records: 60, types: ['HeartRate', 'Steps'], first: null, last: null },
  ],
}

export const reconciliation: ReconciliationResponse = {
  from: '2026-10-15',
  to: '2026-10-15',
  types: ['Steps'],
  summary: { rows: 1, matches: 1, diffs: 0, no_official: 0, overlap_rows: 1 },
  rows: [
    {
      date: '2026-10-15',
      type: 'Steps',
      unit: 'count',
      official: 10200,
      computed: 10200,
      naive: 20056,
      diff: 0,
      diff_pct: 0,
      status: 'match',
      naive_exceeds_official: true,
      sources: [
        { package: 'synthetic.phone', records: 60, raw: 10200, counted: 10200 },
        { package: 'synthetic.watch', records: 54, raw: 9856, counted: 0 },
      ],
    },
  ],
}
