import { queryOptions } from '@tanstack/react-query'
import { api, withQuery } from './client'
import type {
  Agg,
  Bucket,
  DataBounds,
  DaypartResponse,
  ExerciseResponse,
  InventoryResponse,
  OverrideResult,
  ReconciliationResponse,
  ReportDailyResponse,
  ReportResponse,
  SeriesResponse,
  SleepNightsResponse,
  SessionInfo,
  SyncStatusResponse,
  TodaySummary,
} from './types'

const REFRESH_MS = 60_000

export const meQuery = () =>
  queryOptions({
    queryKey: ['me'],
    queryFn: () => api<SessionInfo>('/api/v1/auth/me'),
    staleTime: 5 * 60_000,
    retry: false,
  })

export const summaryQuery = (date?: string) =>
  queryOptions({
    queryKey: ['summary', date ?? 'today'],
    queryFn: () => api<TodaySummary>(withQuery('/api/v1/summary/today', { date })),
    refetchInterval: REFRESH_MS,
  })

export interface SeriesParams {
  type: string
  from: string
  to: string
  bucket?: Bucket
  agg?: Agg
  source?: 'auto' | 'official' | 'computed'
  field?: 'systolic' | 'diastolic'
  band?: boolean
  compare?: boolean
  ma?: boolean
}

export const seriesQuery = (p: SeriesParams) =>
  queryOptions({
    queryKey: ['series', p],
    queryFn: () =>
      api<SeriesResponse>(
        withQuery(`/api/v1/metrics/${encodeURIComponent(p.type)}/series`, {
          from: p.from,
          to: p.to,
          bucket: p.bucket,
          agg: p.agg,
          source: p.source,
          field: p.field,
          band: p.band ? 'true' : undefined,
          compare: p.compare ? 'true' : undefined,
          ma: p.ma ? 'true' : undefined,
        }),
      ),
  })

export const inventoryQuery = () =>
  queryOptions({
    queryKey: ['inventory'],
    queryFn: () => api<InventoryResponse>('/api/v1/data/inventory'),
  })

export const reconciliationQuery = (p: { from: string; to: string; types?: string }) =>
  queryOptions({
    queryKey: ['reconciliation', p],
    queryFn: () => api<ReconciliationResponse>(withQuery('/api/v1/data/reconciliation', p)),
  })

export const syncStatusQuery = () =>
  queryOptions({
    queryKey: ['sync-status'],
    queryFn: () => api<SyncStatusResponse>('/api/v1/sync/status'),
    refetchInterval: REFRESH_MS,
  })

export const boundsQuery = () =>
  queryOptions({
    queryKey: ['bounds'],
    queryFn: () => api<DataBounds>('/api/v1/data/bounds'),
    staleTime: 5 * 60_000,
  })

interface Window {
  from: string
  to: string
}

export const sleepNightsQuery = (w: Window) =>
  queryOptions({
    queryKey: ['sleep-nights', w],
    queryFn: () => api<SleepNightsResponse>(withQuery('/api/v1/sleep/nights', { ...w })),
  })

export const exerciseQuery = (w: Window, scope: 'all' | 'real' = 'all') =>
  queryOptions({
    queryKey: ['exercise', w, scope],
    queryFn: () => api<ExerciseResponse>(withQuery('/api/v1/exercise/sessions', { ...w, scope })),
  })

/** Manual verdict for a session: true / false, or null = back to the automatic rule. */
export const setWorkoutOverride = (id: number, value: boolean | null) =>
  api<OverrideResult>(`/api/v1/exercise/sessions/${id}/override`, { method: 'PUT', body: { value } })

export const reportQuery = (w: Window) =>
  queryOptions({
    queryKey: ['report', w],
    queryFn: () => api<ReportResponse>(withQuery('/api/v1/report', { ...w })),
  })

export const reportDailyQuery = (w: Window, enabled = true) =>
  queryOptions({
    queryKey: ['report-daily', w],
    queryFn: () => api<ReportDailyResponse>(withQuery('/api/v1/report/daily', { ...w })),
    enabled,
  })

export const daypartQuery = (
  w: Window & { bucket?: 'day' | 'week' | 'month'; includeWorkouts?: boolean },
  enabled = true,
) =>
  queryOptions({
    queryKey: ['daypart', w],
    queryFn: () =>
      api<DaypartResponse>(
        withQuery('/api/v1/heart/daypart', {
          from: w.from,
          to: w.to,
          bucket: w.bucket,
          include_workouts: w.includeWorkouts ? 'true' : undefined,
        }),
      ),
    enabled,
  })
