import type { Icon } from '@phosphor-icons/react'
import { ChartLine, DownloadSimple, Table } from '@phosphor-icons/react'
import type { UseQueryResult } from '@tanstack/react-query'
import type { EChartsCoreOption } from 'echarts/core'
import { useReducedMotion } from 'motion/react'
import { type ReactNode, Suspense, lazy, useId, useMemo, useState } from 'react'
import type { SeriesResponse } from '../api/types'
import { t } from '../i18n'
import { baseOption, bucketLabel, bucketLabelLong, describeSeries, palette } from '../lib/charts'
import { downloadCsv, toCsv } from '../lib/csv'
import { fmtNumber } from '../lib/format'
import { type Accent, Panel } from './hud'
import { Async, Skeleton } from './states'

// ECharts is ~400 kB: load it only when a chart is first shown (keeps the login page light).
const EChart = lazy(() => import('./EChart').then((m) => ({ default: m.EChart })))

export interface TableSpec {
  caption: string
  columns: string[]
  rows: (string | number)[][]
}

export interface CsvSpec {
  filename: string
  columns: string[]
  rows: (string | number | null)[][]
}

export interface CursorSpec {
  count: number
  index: number | null
  onChange: (i: number | null) => void
  /** Text of the selected point (also announced to screen readers). */
  readout: string
}

interface ChartFrameProps {
  summary: string
  option: EChartsCoreOption
  height?: number
  table: TableSpec
  csv?: CsvSpec
  /** Rendered above the chart (granularity, toggles). */
  controls?: ReactNode
  cursor?: CursorSpec
  note?: ReactNode
}

/** A chart is never alone: summary above, keyboard cursor, table alternative and CSV export below. */
export function ChartFrame({ summary, option, height = 220, table, csv, controls, cursor, note }: ChartFrameProps) {
  const [showTable, setShowTable] = useState(false)
  const summaryId = useId()
  const cursorId = useId()
  return (
    <div className="flex flex-col gap-2">
      <p id={summaryId} className="text-sm text-fg-muted" data-testid="chart-summary">
        {summary}
      </p>
      {controls}
      {showTable ? (
        <div className="max-h-72 overflow-auto border border-border" tabIndex={0} role="region" aria-label={table.caption}>
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">{table.caption}</caption>
            <thead className="sticky top-0 bg-surface-muted text-left">
              <tr>
                {table.columns.map((c) => (
                  <th key={c} scope="col" className="px-2 py-1 font-normal text-fg-muted">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((r, i) => (
                <tr key={i} className="border-t border-border">
                  {r.map((cell, j) => (
                    <td key={j} className="px-2 py-1">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <Suspense fallback={<Skeleton className="w-full" label={t('state.loading')} />}>
            <EChart
              option={option}
              height={height}
              label={table.caption}
              describedBy={summaryId}
              activeIndex={cursor?.index ?? null}
            />
          </Suspense>
          {cursor && cursor.count > 1 && (
            <div className="flex flex-col gap-1 no-print">
              <label htmlFor={cursorId} className="hud-label">
                {t('chart.cursor')}
              </label>
              <input
                id={cursorId}
                type="range"
                min={0}
                max={cursor.count - 1}
                step={1}
                value={cursor.index ?? 0}
                onChange={(e) => cursor.onChange(Number(e.target.value))}
                onBlur={() => cursor.onChange(null)}
                aria-valuetext={cursor.readout}
                className="h-11 w-full accent-[var(--color-accent-glow)]"
              />
              <p aria-live="polite" className="min-h-5 text-sm" data-testid="chart-readout">
                {cursor.index !== null ? cursor.readout : ''}
              </p>
            </div>
          )}
        </>
      )}
      {note}
      <div className="flex flex-wrap gap-2 no-print">
        <button
          type="button"
          className="btn min-h-11 text-xs"
          aria-pressed={showTable}
          onClick={() => setShowTable((v) => !v)}
        >
          {showTable ? <ChartLine size={16} aria-hidden /> : <Table size={16} aria-hidden />}
          {showTable ? t('chart.hideTable') : t('chart.showTable')}
        </button>
        {csv && (
          <button
            type="button"
            className="btn min-h-11 text-xs"
            onClick={() => downloadCsv(csv.filename, toCsv(csv.columns, csv.rows))}
          >
            <DownloadSimple size={16} aria-hidden />
            {t('chart.exportCsv')}
          </button>
        )}
      </div>
    </div>
  )
}

interface SeriesChartCardProps {
  title: string
  icon: Icon
  accent: Accent
  query: UseQueryResult<SeriesResponse>
  kind: 'bar' | 'line'
  /** Series name used in summary and table, e.g. "Passi". */
  label: string
  color: keyof ReturnType<typeof palette>
  className?: string
  index?: number
  height?: number
  testId?: string
}

/** Panel + loading/error/empty handling + chart + text summary + table for one /metrics series. */
export function SeriesChartCard({
  title,
  icon,
  accent,
  query,
  kind,
  label,
  color,
  className,
  index,
  height = 220,
  testId,
}: SeriesChartCardProps) {
  const reduced = useReducedMotion() ?? false
  const data = query.data
  const built = useMemo(() => {
    if (!data) return null
    const unit = data.unit === 'count' ? '' : (data.unit ?? '')
    const categories = data.points.map((p) => bucketLabel(p.t, data.bucket))
    const option = baseOption(
      categories,
      [{ name: label, color: palette()[color], kind, data: data.points.map((p) => p.v) }],
      { unit, reducedMotion: reduced },
    )
    const table: TableSpec = {
      caption: t('chart.tableCaption', { label, bucket: t(`bucket.${data.bucket}` as const) }),
      columns: [t('chart.col.when'), `${label}${unit ? ` (${unit})` : ''}`],
      rows: data.points.map((p) => [bucketLabelLong(p.t, data.bucket), fmtNumber(p.v, 1)]),
    }
    return { option, table, summary: describeSeries(label, unit, data) }
  }, [data, label, kind, color, reduced])

  return (
    <Panel title={title} icon={icon} accent={accent} className={className} index={index} testId={testId}>
      <Async
        query={query}
        skeleton={<Skeleton className="h-[220px] w-full" label={t('state.loading')} />}
        isEmpty={(d) => d.summary.points === 0}
        emptyTitle={t('chart.empty.title')}
        emptyHint={t('chart.empty.hint')}
      >
        {() => (built ? <ChartFrame summary={built.summary} option={built.option} table={built.table} height={height} /> : null)}
      </Async>
    </Panel>
  )
}
