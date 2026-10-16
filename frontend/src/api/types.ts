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
  lo?: number | null
  hi?: number | null
  ma?: number | null
  prev?: number | null
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
  field: string | null
  coarsened: boolean
  ma_window: number | null
  previous_from: string | null
  previous_to: string | null
  previous_summary: SeriesSummary | null
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

export interface DataBounds {
  first: string | null
  last: string | null
}

export interface SleepNight {
  date: string
  asleep_s: number | null
  in_bed_s: number | null
  stages_s: Record<string, number>
  start: string | null
  end: string | null
  bedtime_min: number | null
  wake_min: number | null
}

export interface SleepStats {
  nights: number
  avg_asleep_s: number | null
  avg_in_bed_s: number | null
  bedtime_avg_min: number | null
  wake_avg_min: number | null
  bedtime_sd_min: number | null
  wake_sd_min: number | null
}

export interface SleepNightsResponse {
  from: string
  to: string
  nights: SleepNight[]
  summary: SleepStats
  previous: SleepStats
}

export interface ExerciseRow {
  id: number
  type: string
  title: string | null
  start: string
  end: string
  duration_s: number
  kcal: number | null
  avg_hr: number | null
  source_package: string
  has_route: boolean
  /** Share (0..1) of the session's minutes with a heart-rate sample. */
  hr_coverage: number | null
  has_hr: boolean
  recording_method: string
  started_by_user: boolean
  /** Verdict of the rule alone / manual verdict (null = automatic) / what counts. */
  auto_real: boolean
  /** Which rule decided the automatic verdict: excluded type, too short, or none. */
  auto_rule: 'type' | 'duration' | 'ok'
  min_duration_min: number
  override: boolean | null
  is_real: boolean
}

export interface ExerciseStats {
  count: number
  duration_s: number
  avg_duration_s: number | null
  kcal: number | null
  by_type: Record<string, number>
}

export interface ExerciseResponse {
  from: string
  to: string
  scope: 'all' | 'real'
  total_count: number
  real_count: number
  sessions: ExerciseRow[]
  weekly: { week_start: string; count: number; duration_s: number; kcal: number }[]
  summary: ExerciseStats
  previous: ExerciseStats
}

export interface PeriodStats {
  days: number
  total: number | null
  avg: number | null
  min: number | null
  max: number | null
}

export interface ReportMetric {
  key: string
  type: string
  unit: string | null
  kind: 'sum' | 'avg' | 'range'
  days_with_data: number
  current: PeriodStats
  previous: PeriodStats
  delta_abs: number | null
  delta_pct: number | null
  higher_is_better: boolean | null
  best_day: { date: string; value: number } | null
  worst_day: { date: string; value: number } | null
  first: number | null
  last: number | null
  spark: (number | null)[]
  spark_bucket: 'day' | 'week' | 'month'
  diastolic: PeriodStats | null
  sessions: number | null
}

export interface ReportResponse {
  from: string
  to: string
  days: number
  previous_from: string
  previous_to: string
  generated_at: string
  timezone: string
  metrics: ReportMetric[]
  sleep_regularity: SleepStats | null
  workouts: {
    count: number
    duration_s: number
    avg_duration_s: number | null
    per_week: number | null
    by_type: Record<string, number>
    scope: 'real'
    excluded: number
  }
}

export interface ReportDailyResponse {
  from: string
  to: string
  columns: { key: string; label: string; unit: string | null }[]
  rows: { date: string; values: Record<string, number | null> }[]
}

export interface NightInterval {
  date: string
  start: string
  end: string
  /** sleep = recorded sleep session(s); fixed = fallback window 23:00-07:00 */
  source: 'sleep' | 'fixed'
}

export interface WorkoutInterval {
  start: string
  end: string
  recovery_end: string
}

export interface OverrideResult {
  id: number
  override: boolean | null
  is_real: boolean
}

export interface DaypartPoint {
  t: string
  day: number | null
  night: number | null
  day_n: number
  night_n: number
}

export interface DaypartStats {
  avg: number | null
  days: number
  samples: number
}

export interface DaypartSummary {
  day: DaypartStats
  night: DaypartStats
}

export interface DaypartResponse {
  from: string
  to: string
  bucket: 'day' | 'week' | 'month'
  timezone: string
  fixed_window: string
  nights: NightInterval[]
  include_workouts: boolean
  /** Real workouts (with 30 min recovery) overlapping the range. */
  workouts: WorkoutInterval[]
  points: DaypartPoint[]
  summary: DaypartSummary
  previous_from: string
  previous_to: string
  previous_summary: DaypartSummary
}

/** The active classification rules, in evaluation order, straight from the backend constants. */
export interface ExerciseRules {
  rules: (
    | { id: 'override'; params: Record<string, never> }
    | { id: 'type'; params: { types: string[] } }
    | { id: 'duration'; params: { min_minutes: number } }
    | { id: 'default'; params: Record<string, never> }
  )[]
  daytime_hr: { excludes: 'real_workouts'; recovery_minutes: number }
  signals: { hr_min_share: number; user_started_methods: string[]; informative_only: boolean }
}

export interface TableStorage {
  name: string
  total_bytes: number
  data_bytes: number
  index_bytes: number
  rows: number
  /** false = catalog estimate, true = exact count */
  rows_exact: boolean
}

export interface LimitItem {
  id:
    | 'retention'
    | 'soft_delete'
    | 'session_purge'
    | 'daily_recompute'
    | 'ingest_batch'
    | 'ingest_body'
    | 'route_points'
    | 'query_days'
    | 'intraday'
    | 'chart_points'
  params: Record<string, number | boolean>
}

export interface StorageResponse {
  database_bytes: number
  postgres_version: string
  tables: TableStorage[]
  records_live: number
  records_deleted: number
  first_data: string | null
  last_data: string | null
  last_ingest: string | null
  growth: {
    window_days: number
    records: number
    samples: number
    bytes: number
    bytes_per_year: number
    estimated: boolean
  }
  disk: { total_bytes: number; used_bytes: number; free_bytes: number; free_percent: number }
  limits: { items: LimitItem[] }
}
