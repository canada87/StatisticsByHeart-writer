import { queryOptions } from '@tanstack/react-query'
import { api, withQuery } from './client'
import type {
  Agg,
  Bucket,
  InventoryResponse,
  ReconciliationResponse,
  SeriesResponse,
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
