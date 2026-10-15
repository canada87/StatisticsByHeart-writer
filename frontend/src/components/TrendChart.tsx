import type { Icon } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useReducedMotion } from 'motion/react'
import { useId, useMemo, useState } from 'react'
import { seriesQuery } from '../api/queries'
import type { Bucket, SeriesResponse } from '../api/types'
import { t } from '../i18n'
import { baseOption, bucketLabel, bucketLabelLong, palette } from '../lib/charts'
import { csvName } from '../lib/csv'
import { describeTrend } from '../lib/delta'
import { fmtNumber } from '../lib/format'
import { type MetricDef, fmtMetric, scaled, withUnit } from '../lib/metrics'
import type { ResolvedRange } from '../lib/range'
import { ChartFrame, type TableSpec } from './ChartCard'
import { type Accent, Panel } from './hud'
import { Async, Skeleton } from './states'

export interface ReferenceBand {
  from: number
  to: number
  label: string
  /** Which line the area is attached to: 0 = main metric, 1 = the paired metric. */
  series?: 0 | 1
}

interface Props {
  def: MetricDef
  /** A second metric drawn on the same chart as a dashed line (blood pressure: diastolic). */
  pair?: MetricDef
  range: ResolvedRange
  icon: Icon
  accent: Accent
  /** Indicative reference areas (display units). Always labelled as indicative, never a diagnosis. */
  reference?: ReferenceBand[]
  referenceNote?: string
  /** Shown instead of the generic empty state (e.g. "turn this metric on in the app"). */
  emptyTitle?: string
  emptyHint?: string
  className?: string
  index?: number
  height?: number
}

const BUCKETS: Exclude<Bucket, '15min' | 'hour'>[] = ['auto', 'day', 'week', 'month']
const BUCKET_LABEL = {
  auto: 'bucket.opt.auto',
  day: 'bucket.opt.day',
  week: 'bucket.opt.week',
  month: 'bucket.opt.month',
} as const

const MA_UNIT: Record<string, string> = { day: 'g', week: ' sett.', month: ' mesi' }

/** Client default: server-automatic only for 24h (intraday) and very long ranges, else per day. */
export function defaultBucket(days: number): Bucket {
  return days <= 1 || days > 120 ? 'auto' : 'day'
}

function trendSentence(values: (number | null)[]): string {
  const trend = describeTrend(values)
  if (trend === null) return ''
  return t(`trend.${trend}` as const)
}

/**
 * Trend chart for one metric: granularity selector, optional 7-day moving average (dashed),
 * optional previous-period line (dotted), keyboard-reachable values, text summary, table, CSV.
 */
export function TrendChart({
  def,
  pair,
  range,
  icon,
  accent,
  reference,
  referenceNote,
  emptyTitle,
  emptyHint,
  className,
  index,
  height = 260,
}: Props) {
  const reduced = useReducedMotion() ?? false
  const [bucket, setBucket] = useState<Bucket>('auto')
  const [showMa, setShowMa] = useState(false)
  const [showPrev, setShowPrev] = useState(false)
  const [cursor, setCursor] = useState<number | null>(null)
  const bucketId = useId()
  const effective: Bucket = bucket === 'auto' ? defaultBucket(range.days) : bucket

  const query = useQuery(
    seriesQuery({
      type: def.type,
      field: def.field,
      from: range.from,
      to: range.to,
      bucket: effective,
      agg: def.agg,
      band: def.band,
      compare: true,
      ma: true,
    }),
  )

  const query2 = useQuery({
    ...seriesQuery({
      type: (pair ?? def).type,
      field: pair?.field,
      from: range.from,
      to: range.to,
      bucket: effective,
      agg: (pair ?? def).agg,
    }),
    enabled: !!pair,
  })

  const built = useMemo(() => {
    const d: SeriesResponse | undefined = query.data
    if (!d) return null
    const d2: SeriesResponse | undefined = pair ? query2.data : undefined
    const label2 = pair ? t(pair.label) : ''
    const pairData = pair && d2 ? d2.points.map((x) => scaled(pair, x.v)) : null
    const label = t(def.label)
    const p = palette()
    const pts = d.points
    const main = pts.map((x) => scaled(def, x.v))
    const ma = d.ma_window ? pts.map((x) => scaled(def, x.ma ?? null)) : null
    const prev = pts.map((x) => scaled(def, x.prev ?? null))
    const hasPrev = d.previous_summary !== null && d.previous_summary.points > 0
    const hasBand = !!def.band && pts.some((x) => x.lo != null)
    const maN = `${d.ma_window ?? 7}${MA_UNIT[d.bucket] ?? ''}`
    const maName = t('chart.ma', { n: maN })
    const prevName = t('chart.prev')
    const bandName = t('chart.band')
    const unit = def.unit

    const option = baseOption(
      pts.map((x) => bucketLabel(x.t, d.bucket)),
      [
        { name: label, color: p[def.color], kind: def.kind, data: main, short: pair ? t('bp.short.sys') : undefined },
        ...(pair && pairData
          ? [
              {
                name: label2,
                color: p[pair.color],
                kind: 'line' as const,
                dashed: true,
                data: pairData,
                short: t('bp.short.dia'),
              },
            ]
          : []),
        ...(showMa && ma ? [{ name: maName, color: p.fg, kind: 'line' as const, dashed: true, data: ma, short: t('chart.ma.short', { n: maN }) }] : []),
        ...(showPrev && hasPrev
          ? [{ name: prevName, color: p.muted, kind: 'line' as const, dotted: true, data: prev, short: t('chart.prev.short') }]
          : []),
      ],
      { unit, showLegend: true, reducedMotion: reduced, endLabels: true },
    ) as Record<string, unknown> & { series: Record<string, unknown>[]; legend: Record<string, unknown> }

    if (hasBand) {
      const lo = pts.map((x) => scaled(def, x.lo ?? null))
      const span = pts.map((x) =>
        x.lo != null && x.hi != null ? (x.hi - x.lo) * def.scale : null,
      )
      option.series.push(
        { name: '_lo', type: 'line', stack: 'band', data: lo, symbol: 'none', silent: true, lineStyle: { opacity: 0 }, tooltip: { show: false } },
        { name: bandName, type: 'line', stack: 'band', data: span, symbol: 'none', silent: true, lineStyle: { opacity: 0 }, areaStyle: { color: p[def.color], opacity: 0.16 } },
      )
      option.legend = { ...option.legend, data: [label, bandName, ...(showMa && ma ? [maName] : []), ...(showPrev && hasPrev ? [prevName] : [])] }
    }
    for (const which of [0, 1] as const) {
      const refs = (reference ?? []).filter((r) => (r.series ?? 0) === which)
      const target = option.series[which] as Record<string, unknown> | undefined
      if (!refs.length || !target) continue
      target.markArea = {
        silent: true,
        itemStyle: { color: which === 0 ? 'rgba(52, 211, 153, 0.09)' : 'rgba(96, 165, 250, 0.09)' },
        label: { color: p.muted, position: 'insideTopLeft', fontSize: 11 },
        data: refs.map((r) => [{ yAxis: r.from, name: r.label }, { yAxis: r.to }]),
      }
    }
    option.tooltip = {
      ...(option.tooltip as object),
      formatter: (params: { dataIndex: number }[]) => {
        const i = params[0]?.dataIndex ?? 0
        const x = pts[i]
        if (!x) return ''
        const line = (name: string, v: number | null | undefined, digits = def.digits) =>
          v == null ? '' : `<div>${name}: <b>${withUnit(def, fmtNumber(v * def.scale, digits))}</b></div>`
        return [
          `<div>${bucketLabelLong(x.t, d.bucket)}</div>`,
          line(label, x.v),
          pair && d2 ? line(label2, d2.points[i]?.v, pair.digits) : '',
          hasBand && x.lo != null && x.hi != null
            ? `<div>${bandName}: <b>${fmtMetric(def, x.lo)}–${withUnit(def, fmtMetric(def, x.hi))}</b></div>`
            : '',
          showMa ? line(maName, x.ma) : '',
          showPrev ? line(prevName, x.prev) : '',
        ].join('')
      },
    }

    const columns = [
      t('chart.col.when'),
      withUnit(def, label).replace(/^(.*) (\S+)$/, '$1 ($2)') || label,
      ...(pair ? [withUnit(pair, label2).replace(/^(.*) (\S+)$/, '$1 ($2)')] : []),
      ...(hasBand ? [t('chart.col.min'), t('chart.col.max')] : []),
      ...(ma ? [maName] : []),
      ...(hasPrev ? [prevName] : []),
    ]
    const toRow = (x: SeriesResponse['points'][number], i: number) => [
      x.t,
      ...[x.v, ...(pair ? [d2?.points[i]?.v ?? null] : []), ...(hasBand ? [x.lo ?? null, x.hi ?? null] : []), ...(ma ? [x.ma ?? null] : []), ...(hasPrev ? [x.prev ?? null] : [])].map(
        (v) => (v == null ? null : Math.round(v * def.scale * 1000) / 1000),
      ),
    ]
    const table: TableSpec = {
      caption: t('chart.tableCaption', { label, bucket: t(`bucket.${d.bucket}` as const) }),
      columns,
      rows: pts.map((x, i) => [
        bucketLabelLong(x.t, d.bucket),
        ...toRow(x, i)
          .slice(1)
          .map((v) => (typeof v === 'number' ? fmtNumber(v, def.digits) : '—')),
      ]),
    }
    const csv = {
      filename: csvName(def.id, d.from, d.to, d.bucket),
      columns: [t('chart.col.date'), ...columns.slice(1)],
      rows: pts.map((x, i) => toRow(x, i)),
    }

    const s = d.summary
    const total = d.agg === 'sum'
    const parts = [
      t('chart.summary.head', { label, count: s.points, bucket: t(`bucket.${d.bucket}` as const) }),
      total && s.total !== null ? t('chart.summary.total', { value: withUnit(def, fmtMetric(def, s.total)) }) : '',
      s.avg !== null ? t('chart.summary.avg', { value: withUnit(def, fmtMetric(def, s.avg)) }) : '',
      s.min !== null && s.max !== null
        ? t('chart.summary.range', { min: fmtMetric(def, s.min), max: withUnit(def, fmtMetric(def, s.max)) })
        : '',
      pair && d2?.summary.avg != null
        ? t('chart.summary.pair', { label: label2, value: withUnit(pair, fmtMetric(pair, d2.summary.avg)) })
        : '',
      trendSentence(main),
      d.previous_summary?.avg != null && s.avg !== null
        ? t('chart.summary.prev', { value: withUnit(def, fmtMetric(def, d.previous_summary.avg)) })
        : '',
    ]
    const readout = (i: number) => {
      const x = pts[i]
      if (!x) return ''
      return [
        bucketLabelLong(x.t, d.bucket),
        x.v === null ? t('chart.noValue') : withUnit(def, fmtMetric(def, x.v)),
        showMa && x.ma != null ? `${maName}: ${fmtMetric(def, x.ma)}` : '',
        showPrev && x.prev != null ? `${prevName}: ${fmtMetric(def, x.prev)}` : '',
      ]
        .filter(Boolean)
        .join(' · ')
    }
    return { option, table, csv, summary: parts.filter(Boolean).join(' '), readout, d, hasPrev, hasMa: !!ma }
  }, [query.data, query2.data, def, pair, showMa, showPrev, reduced, reference])

  const controls = built && (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 no-print" data-testid="trend-controls">
      <div className="flex items-center gap-2">
        <label htmlFor={bucketId} className="hud-label">
          {t('chart.granularity')}
        </label>
        {range.days <= 1 ? (
          <span className="text-sm" data-testid="granularity">
            {t(`bucket.${built.d.bucket}` as const)}
          </span>
        ) : (
          <select
            id={bucketId}
            className="input w-auto"
            value={bucket}
            onChange={(e) => {
              setBucket(e.target.value as Bucket)
              setCursor(null)
            }}
          >
            {BUCKETS.map((b) => (
              <option key={b} value={b}>
                {t(BUCKET_LABEL[b])}
              </option>
            ))}
          </select>
        )}
        <span className="text-sm text-fg-muted" data-testid="granularity-actual">
          {range.days > 1 && `→ ${t(`bucket.${built.d.bucket}` as const)}`}
        </span>
      </div>
      {built.hasMa && (
        <button type="button" className="btn min-h-11 text-xs" aria-pressed={showMa} onClick={() => setShowMa((v) => !v)}>
          {t('chart.ma', { n: `${built.d.ma_window ?? 7}${MA_UNIT[built.d.bucket] ?? ''}` })}
        </button>
      )}
      <button
        type="button"
        className="btn min-h-11 text-xs"
        aria-pressed={showPrev}
        disabled={!built.hasPrev}
        title={built.hasPrev ? undefined : t('chart.prev.none')}
        onClick={() => setShowPrev((v) => !v)}
      >
        {t('chart.prev')}
      </button>
    </div>
  )

  return (
    <Panel title={t(def.label)} icon={icon} accent={accent} className={className} index={index} testId={`trend-${def.id}`}>
      <Async
        query={query}
        skeleton={<Skeleton className="h-[260px] w-full" label={t('state.loading')} />}
        isEmpty={(d) => d.summary.points === 0}
        emptyTitle={emptyTitle ?? t('chart.empty.title')}
        emptyHint={emptyHint ?? t('chart.empty.hint')}
      >
        {() =>
          built && (
            <ChartFrame
              summary={built.summary}
              option={built.option}
              table={built.table}
              csv={built.csv}
              height={height}
              controls={controls}
              cursor={{
                count: built.d.points.length,
                index: cursor,
                onChange: setCursor,
                readout: cursor === null ? '' : built.readout(cursor),
              }}
              note={
                <>
                  {built.d.coarsened && (
                    <p className="text-xs text-warn" data-testid="coarsened-note">
                      {t('chart.coarsened', { bucket: t(`bucket.${built.d.bucket}` as const) })}
                    </p>
                  )}
                  {reference?.length ? (
                    <p className="text-xs text-fg-muted" data-testid="reference-note">
                      {referenceNote}
                    </p>
                  ) : null}
                </>
              }
            />
          )
        }
      </Async>
    </Panel>
  )
}
