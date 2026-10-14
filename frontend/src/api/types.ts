// Mirrors backend/app/dash_schemas.py (dashboard read API). The Reader contract is separate.

export type DailySource = 'hc_official' | 'computed'

export interface MetricValue {
  value: number | null
  unit: string | null
  date: string | null
  source: DailySource | null
  official: number | null
  computed: number | null
}

export interface LatestSample {
  time: string
  value: number
}

export interface HeartSummary {
  current: LatestSample | null
  resting: MetricValue
  avg: number | null
  min: number | null
  max: number | null
  samples: number
}

export interface SleepSummary {
  date: string
  asleep_s: number | null
  official_asleep_s: number | null
  computed_asleep_s: number | null
  in_bed_s: number | null
  stages_s: Record<string, number>
  start: string | null
  end: string | null
  sessions: number
}

export interface ActivityItem {
  id: number
  type: string
  title: string | null
  start: string
  end: string
  duration_s: number
  source_package: string
  has_route: boolean
}

export interface TodaySummary {
  date: string
  timezone: string
  generated_at: string
  steps: MetricValue
  distance_m: MetricValue
  active_kcal: MetricValue
  total_kcal: MetricValue
  heart: HeartSummary
  sleep: SleepSummary | null
  spo2: MetricValue
  hrv: MetricValue
  activities: ActivityItem[]
  last_sync_at: string | null
}

export type Bucket = 'auto' | '15min' | 'hour' | 'day' | 'week' | 'month'
export type Agg = 'sum' | 'avg' | 'min' | 'max' | 'count'

export interface SeriesPoint {
  t: string
  v: number | null
  n: number | null
}

export interface SeriesSummary {
  points: number
  min: number | null
  max: number | null
  avg: number | null
  total: number | null
  first: number | null
  last: number | null
}

export interface SeriesResponse {
  type: string
  unit: string | null
  bucket: Exclude<Bucket, 'auto'>
  agg: Agg
  from: string
  to: string
  timezone: string
  source: 'auto' | 'official' | 'computed'
  source_counts: Record<string, number>
  points: SeriesPoint[]
  summary: SeriesSummary
}

export interface SourceInventory {
  package: string
  records: number
  first: string | null
  last: string | null
}

export interface TypeInventory {
  type: string
  unit: string | null
  shape: string
  records: number
  deleted: number
  samples: number
  first: string | null
  last: string | null
  official_days: number
  computed_days: number
  sources: SourceInventory[]
}

export interface SourceTotals {
  package: string
  records: number
  types: string[]
  first: string | null
  last: string | null
}

export interface InventoryResponse {
  generated_at: string
  records: number
  deleted: number
  samples: number
  types: TypeInventory[]
  sources: SourceTotals[]
}

export interface SourceBreakdown {
  package: string
  records: number
  raw: number
  counted: number | null
}

export type ReconStatus = 'match' | 'diff' | 'no_official' | 'no_computed' | 'no_data'

export interface ReconciliationRow {
  date: string
  type: string
  unit: string | null
  official: number | null
  computed: number | null
  naive: number | null
  diff: number | null
  diff_pct: number | null
  status: ReconStatus
  naive_exceeds_official: boolean
  sources: SourceBreakdown[]
}

export interface ReconciliationResponse {
  from: string
  to: string
  types: string[]
  rows: ReconciliationRow[]
  summary: {
    rows: number
    matches: number
    diffs: number
    no_official: number
    overlap_rows: number
  }
}

export interface RejectionTally {
  type: string
  reason: string
  count: number
  detail: string | null
}

export interface SyncRunRow {
  sync_id: string
  device_id: string
  device_name: string | null
  mode: string | null
  status: 'running' | 'completed' | 'partial' | 'failed'
  started_at: string
  finished_at: string | null
  duration_s: number | null
  last_activity_at: string
  received: number
  inserted: number
  updated: number
  unchanged: number
  rejected: number
  deletions: number
  aggregates: number
  reported_counts: Record<string, number> | null
  rejections: RejectionTally[]
  errors: { code: string; message?: string; type?: string; count?: number }[]
}

export interface DeviceRow {
  id: string
  name: string | null
  model: string | null
  app_version: string | null
  first_seen_at: string
  last_seen_at: string
}

export interface SyncStatusResponse {
  generated_at: string
  last_success_at: string | null
  last_activity_at: string | null
  devices: DeviceRow[]
  runs: SyncRunRow[]
}

export interface SessionInfo {
  username: string
  expires_at: string
}
