import { ArrowClockwise, Tray, WarningOctagon } from '@phosphor-icons/react'
import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import { t } from '../i18n'

export function Skeleton({ className = '', label }: { className?: string; label?: string }) {
  return (
    <div
      className={`skeleton ${className}`}
      role="status"
      aria-label={label ?? t('state.loading')}
      aria-busy="true"
    />
  )
}

/** Reserved-height skeleton blocks so data arriving later never shifts the layout. */
export function SkeletonLines({ lines = 3, height = 'h-5' }: { lines?: number; height?: string }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true" role="status" aria-label={t('state.loading')}>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className={`skeleton ${height}`} style={{ width: `${100 - i * 12}%` }} />
      ))}
    </div>
  )
}

export function EmptyState({ title, hint }: { title?: string; hint?: string }) {
  return (
    <div className="flex flex-col items-start gap-2 py-4 text-fg-muted" data-testid="empty-state">
      <Tray size={28} aria-hidden />
      <p className="text-fg">{title ?? t('state.empty')}</p>
      {hint && <p className="text-sm">{hint}</p>}
    </div>
  )
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 0) return t('state.error.network')
    return `${error.message} (${error.status})`
  }
  return t('state.error.generic')
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-3 py-2" data-testid="error-state">
      <div className="flex items-start gap-2 text-danger-text">
        <WarningOctagon size={24} aria-hidden className="shrink-0" />
        <span>{errorText(error)}</span>
      </div>
      <button type="button" className="btn" onClick={onRetry}>
        <ArrowClockwise size={18} aria-hidden />
        {t('state.retry')}
      </button>
    </div>
  )
}

interface AsyncProps<T> {
  query: UseQueryResult<T>
  skeleton?: ReactNode
  isEmpty?: (data: T) => boolean
  emptyTitle?: string
  emptyHint?: string
  children: (data: T) => ReactNode
}

/** Loading (skeleton) / error (retry) / empty / content: the four states every panel handles. */
export function Async<T>({ query, skeleton, isEmpty, emptyTitle, emptyHint, children }: AsyncProps<T>) {
  if (query.isPending) return <>{skeleton ?? <SkeletonLines />}</>
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  if (isEmpty?.(query.data)) return <EmptyState title={emptyTitle} hint={emptyHint} />
  return <>{children(query.data)}</>
}
