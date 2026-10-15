import type { SeriesResponse } from '../api/types'
import { t } from '../i18n'
import { fmtDay, fmtDayShort, fmtNumber, fmtTime } from './format'

function cssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

export const palette = () => ({
  fg: cssVar('--color-fg', '#f8fafc'),
  muted: cssVar('--color-fg-muted', '#94a3b8'),
  grid: cssVar('--color-border', '#1e293b'),
  axis: cssVar('--color-border-control', '#64748b'),
  surface: cssVar('--color-surface', '#1e1e23'),
  glow: cssVar('--color-accent-glow', '#22d3ee'),
  heart: cssVar('--color-m-heart', '#ff3b6b'),
  sleep: cssVar('--color-m-sleep-text', '#a78bfa'),
  energy: cssVar('--color-m-energy', '#fbbf24'),
  vitals: cssVar('--color-m-vitals', '#34d399'),
  accent: cssVar('--color-accent', '#3b82f6'),
  warn: cssVar('--color-warn', '#fbbf24'),
})

/** x-axis label for a bucket start (a day or a local datetime). */
export function bucketLabel(t_: string, bucket: SeriesResponse['bucket']): string {
  if (bucket === 'day' || bucket === 'week' || bucket === 'month') return fmtDayShort(t_)
  return fmtTime(t_)
}

export function bucketLabelLong(t_: string, bucket: SeriesResponse['bucket']): string {
  if (bucket === 'day' || bucket === 'week' || bucket === 'month') return fmtDay(t_)
  return `${fmtDay(t_.slice(0, 10))} ${fmtTime(t_)}`
}

export interface ChartSeries {
  name: string
  color: string
  kind: 'bar' | 'line'
  data: (number | null)[]
  dashed?: boolean
  dotted?: boolean
  /** Short direct label drawn at the end of a line (in addition to the legend). */
  short?: string
}

/** Shared axis/grid/tooltip styling so every chart in the app looks like one system. */
export function baseOption(
  categories: string[],
  series: ChartSeries[],
  opts: { unit?: string; showLegend?: boolean; reducedMotion?: boolean; endLabels?: boolean } = {},
) {
  const p = palette()
  const unit = opts.unit ? ` ${opts.unit}` : ''
  return {
    animation: !opts.reducedMotion,
    animationDuration: 300,
    textStyle: { fontFamily: "'Fira Code', ui-monospace, monospace", color: p.muted },
    grid: {
      left: 8,
      right: opts.endLabels ? 68 : 12,
      top: opts.showLegend ? 36 : 12,
      bottom: 4,
      containLabel: true,
    },
    legend: opts.showLegend
      ? { top: 0, textStyle: { color: p.fg, fontFamily: "'Fira Code', monospace" }, icon: 'rect' }
      : { show: false },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.surface,
      borderColor: p.axis,
      textStyle: { color: p.fg, fontFamily: "'Fira Code', monospace" },
      valueFormatter: (v: unknown) => (typeof v === 'number' ? `${fmtNumber(v, 1)}${unit}` : '—'),
    },
    xAxis: {
      type: 'category',
      data: categories,
      axisLine: { lineStyle: { color: p.axis } },
      axisLabel: { color: p.muted, hideOverlap: true },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      name: opts.unit && opts.unit !== 'count' ? opts.unit : undefined,
      nameTextStyle: { color: p.muted, align: 'left' },
      axisLabel: { color: p.muted, formatter: (v: number) => fmtNumber(v, 1) },
      scale: series.every((s) => s.kind === 'line'),
      splitLine: { lineStyle: { color: p.grid } },
    },
    series: series.map((s) => ({
      name: s.name,
      type: s.kind,
      data: s.data,
      itemStyle: { color: s.color },
      lineStyle: {
        color: s.color,
        width: 2,
        type: s.dashed ? 'dashed' : s.dotted ? 'dotted' : 'solid',
      },
      areaStyle:
        s.kind === 'line' && !s.dashed && !s.dotted ? { color: s.color, opacity: 0.2 } : undefined,
      endLabel:
        opts.endLabels && s.kind === 'line'
          ? {
              show: true,
              formatter: s.short ?? (s.name.length > 11 ? `${s.name.slice(0, 10)}…` : s.name),
              color: s.color,
              fontSize: 11,
              fontFamily: "'Fira Code', monospace",
            }
          : undefined,
      // sparse series (weight, blood pressure) keep their points visible and joined
      showSymbol: s.kind === 'line' && s.data.filter((v) => v !== null).length <= 60,
      symbol: s.dashed || s.dotted ? 'none' : 'circle',
      symbolSize: 5,
      barMaxWidth: 28,
      connectNulls: s.kind === 'line',
    })),
  }
}

/** Plain-language summary read by assistive tech (and shown above the chart). */
export function describeSeries(label: string, unit: string, s: SeriesResponse): string {
  const sm = s.summary
  if (sm.points === 0) return t('chart.noData', { label })
  const top = s.points.reduce<{ v: number; t: string } | null>(
    (best, p) => (p.v !== null && (best === null || p.v > best.v) ? { v: p.v, t: p.t } : best),
    null,
  )
  const u = unit && unit !== 'count' ? ` ${unit}` : ''
  const parts = [
    t('chart.summary.head', { label, count: sm.points, bucket: t(`bucket.${s.bucket}` as const) }),
  ]
  if (s.agg === 'sum' && sm.total !== null) {
    parts.push(t('chart.summary.total', { value: `${fmtNumber(sm.total)}${u}` }))
  }
  if (sm.avg !== null) parts.push(t('chart.summary.avg', { value: `${fmtNumber(sm.avg, 1)}${u}` }))
  if (top) {
    parts.push(
      t('chart.summary.max', {
        value: `${fmtNumber(top.v, 1)}${u}`,
        when: bucketLabelLong(top.t, s.bucket),
      }),
    )
  }
  return parts.join(' ')
}
