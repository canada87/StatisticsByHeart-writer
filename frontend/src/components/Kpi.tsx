import { ArrowDown, ArrowUp, Equals, Minus } from '@phosphor-icons/react'
import type { UseQueryResult } from '@tanstack/react-query'
import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import type { ReportMetric, ReportResponse } from '../api/types'
import { t } from '../i18n'
import { type Delta, describeDelta } from '../lib/delta'
import { fmtNumber } from '../lib/format'
import { type MetricDef, fmtMetric } from '../lib/metrics'
import { ErrorState, Skeleton } from './states'

const DELTA_ICON = { up: ArrowUp, down: ArrowDown, flat: Equals, none: Minus } as const

/** Arrow + text + screen-reader sentence: the direction is never carried by colour alone. */
export function DeltaBadge({ delta, compact = false }: { delta: Delta; compact?: boolean }) {
  const Icon = DELTA_ICON[delta.direction]
  const short =
    delta.pct !== null && delta.direction !== 'flat'
      ? `${delta.pct > 0 ? '+' : '−'}${fmtNumber(Math.abs(delta.pct), 1)}%`
      : delta.direction === 'flat'
        ? t('delta.flat.short')
        : delta.text
  return (
    <span className="inline-flex items-center gap-1 text-sm text-accent-text" data-testid="delta" data-direction={delta.direction}>
      <Icon size={16} weight="bold" aria-hidden />
      <span aria-hidden>{compact ? short : delta.text}</span>
      <span className="sr-only">{delta.sr}</span>
    </span>
  )
}

export interface KpiSpec {
  id: string
  label: string
  value: string
  unit?: string
  delta?: Delta
  stats?: { label: string; value: string }[]
  hint?: ReactNode
}

export function KpiCard({ spec, index = 0 }: { spec: KpiSpec; index?: number }) {
  return (
    <motion.li
      className="hud-panel flex min-w-0 flex-col gap-2"
      data-testid={`kpi-${spec.id}`}
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: Math.min(index, 6) * 0.04, ease: [0.22, 1, 0.36, 1] }}
    >
      <div className="hud-label">{spec.label}</div>
      <div className="flex items-baseline gap-2">
        <span className="hud-number text-4xl" data-testid="kpi-value">
          {spec.value}
        </span>
        {spec.unit && <span className="text-sm text-fg-muted">{spec.unit}</span>}
      </div>
      {spec.delta && <DeltaBadge delta={spec.delta} />}
      {spec.stats && (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
          {spec.stats.map((s) => (
            <div key={s.label} className="contents">
              <dt className="text-fg-muted">{s.label}</dt>
              <dd className="text-right">{s.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {spec.hint && <div className="text-xs text-fg-muted">{spec.hint}</div>}
    </motion.li>
  )
}

export function KpiGrid({ items }: { items: KpiSpec[] }) {
  return (
    <ul
      className={`mb-3 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2 ${items.length === 6 ? 'xl:grid-cols-3' : 'xl:grid-cols-4'}`}
      aria-label={t('kpi.title')}
    >
      {items.map((spec, i) => (
        <KpiCard key={spec.id} spec={spec} index={i} />
      ))}
    </ul>
  )
}

export function KpiSkeleton({ count = 4 }: { count?: number }) {
  return (
    <ul className="mb-3 grid list-none grid-cols-1 gap-3 p-0 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: count }, (_, i) => (
        <li key={i} className="hud-panel">
          <Skeleton className="h-[104px] w-full" />
        </li>
      ))}
    </ul>
  )
}

/** KPI card for a /report metric: total for cumulative metrics, mean otherwise, with min/max or avg. */
export function metricKpi(def: MetricDef, m: ReportMetric | undefined): KpiSpec {
  const label = t(def.label)
  if (!m || m.days_with_data === 0) {
    return { id: def.id, label, value: '—', unit: def.unit, hint: t('kpi.noData') }
  }
  const dia = def.id === 'diastolic' ? m.diastolic : null
  const cur = dia ?? m.current
  const prev = def.id === 'diastolic' ? null : m.previous
  const sum = m.kind === 'sum'
  const main = sum ? cur.total : cur.avg
  const prevMain = prev ? (sum ? prev.total : prev.avg) : null
  const fmt = (v: number | null) => fmtMetric(def, v)
  const stats = sum
    ? [
        { label: t('kpi.avgDay'), value: fmt(cur.avg) },
        { label: t('kpi.maxDay'), value: fmt(cur.max) },
      ]
    : [
        { label: t('kpi.min'), value: fmt(cur.min) },
        { label: t('kpi.max'), value: fmt(cur.max) },
      ]
  return {
    id: def.id,
    label: sum ? `${label} · ${t('kpi.total')}` : `${label} · ${t('kpi.avg')}`,
    value: fmt(main),
    unit: def.unit,
    delta: describeDelta(main, prevMain),
    stats,
    hint: t('kpi.days', { n: m.days_with_data, prev: fmtNumber(m.previous.days) }),
  }
}

interface KpiSectionProps {
  report: UseQueryResult<ReportResponse>
  defs: MetricDef[]
  /** Extra cards built by the page (sleep schedule, workouts...). */
  extra?: KpiSpec[]
}

export function KpiSection({ report, defs, extra = [] }: KpiSectionProps) {
  if (report.isPending) return <KpiSkeleton count={defs.length + extra.length} />
  if (report.isError) {
    return (
      <div className="hud-panel mb-3">
        <ErrorState error={report.error} onRetry={() => void report.refetch()} />
      </div>
    )
  }
  const byKey = new Map(report.data.metrics.map((m) => [m.key, m]))
  return <KpiGrid items={[...defs.map((d) => metricKpi(d, byKey.get(d.reportKey))), ...extra]} />
}
