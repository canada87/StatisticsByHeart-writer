import { Lightning, ListChecks, Warning } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useReducedMotion } from 'motion/react'
import { useId, useMemo, useState } from 'react'
import { pointsRulesQuery, pointsSeriesQuery, pointsWeekQuery } from '../api/queries'
import type { PointsRules, PointsSeriesResponse, PointsWeek } from '../api/types'
import { t } from '../i18n'
import { baseOption, palette } from '../lib/charts'
import { csvName } from '../lib/csv'
import { fmtDay, fmtDayShort, fmtNumber } from '../lib/format'
import type { ResolvedRange } from '../lib/range'
import { ChartFrame, type TableSpec } from './ChartCard'
import { Ring } from './gauges'
import { Panel } from './hud'
import { Async, SkeletonLines, Skeleton } from './states'

const BUCKETS = ['day', 'week', 'month', 'year'] as const
type PointsBucket = (typeof BUCKETS)[number]

const monthFmt = new Intl.DateTimeFormat('it-IT', { timeZone: 'UTC', month: 'short', year: '2-digit' })

/** 7 and 30 day windows read best per day; longer ones per week (the previous default). */
export function defaultPointsBucket(days: number): PointsBucket {
  return days <= 30 ? 'day' : 'week'
}

function bucketText(day: string, bucket: PointsBucket): string {
  if (bucket === 'year') return day.slice(0, 4)
  if (bucket === 'month') return monthFmt.format(new Date(`${day}T00:00:00Z`))
  return fmtDayShort(day)
}

function bucketLong(day: string, bucket: PointsBucket): string {
  if (bucket === 'year') return day.slice(0, 4)
  if (bucket === 'month') return monthFmt.format(new Date(`${day}T00:00:00Z`))
  return t('points.weekOf', { day: fmtDay(day) })
}

/** The warning shown wherever points are read: no HRmax means cadence points only. */
export function HrMaxWarning() {
  return (
    <p className="flex items-start gap-2 text-xs text-warn" role="note" data-testid="points-hr-warning">
      <Warning size={16} className="mt-0.5 shrink-0" aria-hidden />
      <span>{t('points.warn.noHrMax')}</span>
    </p>
  )
}

// --------------------------------------------------------------------------- Overview card

function WeekBody({ w }: { w: PointsWeek }) {
  const range = `${fmtDayShort(w.week_start)} – ${fmtDayShort(w.week_end)}`
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-4">
        <Ring
          fraction={w.total / w.goal}
          size={124}
          color="var(--color-m-heart, #ff3b6b)"
          label={t('points.ringLabel', { value: fmtNumber(w.total), goal: fmtNumber(w.goal) })}
        >
          <span className="hud-number text-3xl" data-testid="points-value">
            {fmtNumber(w.total)}
          </span>
          <span className="hud-label">{t('points.unit')}</span>
        </Ring>
        <div className="flex min-w-0 flex-col gap-1 text-sm">
          <div>
            <span className="text-fg-muted">{t('points.goal')} </span>
            <b data-testid="points-goal">{fmtNumber(w.goal)}</b>
          </div>
          <div data-testid="points-remaining">
            {w.reached
              ? t('points.reached')
              : w.is_current
                ? t('points.remaining', { n: fmtNumber(w.remaining), days: fmtNumber(w.days_left) })
                : t('points.remainingPast', { n: fmtNumber(w.remaining) })}
          </div>
          <div className="text-xs text-fg-muted" data-testid="points-week">
            {t(w.is_current ? 'points.weekCurrent' : 'points.weekOf', { day: range })}
          </div>
        </div>
      </div>
      {!w.hr_configured && <HrMaxWarning />}
    </div>
  )
}

export function HeartPointsWeekPanel({ day, index = 0 }: { day: string; index?: number }) {
  const q = useQuery(pointsWeekQuery(day))
  return (
    <Panel title={t('points.title.week')} icon={Lightning} accent="heart" className="flex-1" index={index} testId="panel-heartpoints">
      <Async query={q} skeleton={<div className="min-h-32"><SkeletonLines lines={3} height="h-8" /></div>}>
        {(w) => <WeekBody w={w} />}
      </Async>
    </Panel>
  )
}

// --------------------------------------------------------------------------- Cuore: bar chart

function buildChart(d: PointsSeriesResponse, reduced: boolean) {
  const bucket: PointsBucket = d.bucket // what the server really used (it may have widened it)
  const p = palette()
  const label = t('points.title')
  const pts = d.points
  const option = baseOption(
    pts.map((x) => bucketText(x.t, bucket)),
    [{ name: label, color: p.heart, kind: 'bar', data: pts.map((x) => x.v) }],
    { unit: t('points.unit'), showLegend: true, reducedMotion: reduced },
  ) as Record<string, unknown> & { series: Record<string, unknown>[] }
  const ref = Math.round(d.daily_reference)
  if (bucket === 'day') {
    // an indicative reference (goal / 7), dashed and labelled: never presented as a goal
    ;(option.series[0] as Record<string, unknown>).markLine = {
      silent: true,
      symbol: 'none',
      lineStyle: { color: p.warn, type: 'dashed', width: 2 },
      label: { color: p.warn, formatter: t('points.refLine', { ref: fmtNumber(ref), goal: fmtNumber(d.weekly_goal) }), position: 'insideEndTop' },
      data: [{ yAxis: d.daily_reference }],
    }
  }
  if (bucket === 'week') {
    // the weekly goal as a dashed line with its own label (not just a colour)
    ;(option.series[0] as Record<string, unknown>).markLine = {
      silent: true,
      symbol: 'none',
      lineStyle: { color: p.warn, type: 'dashed', width: 2 },
      label: { color: p.warn, formatter: t('points.goalLine', { goal: fmtNumber(d.weekly_goal) }), position: 'insideEndTop' },
      data: [{ yAxis: d.weekly_goal }],
    }
  }
  const s = d.summary
  const weekly = bucket === 'week'
  const parts = [
    t('points.summary.head', { total: fmtNumber(s.total), n: fmtNumber(pts.length), bucket: t(`points.bucket.${bucket}.many` as const) }),
    weekly && s.weeks_over_goal !== null && s.buckets_complete > 0
      ? t('points.summary.goal', { over: fmtNumber(s.weeks_over_goal), total: fmtNumber(s.buckets_complete), goal: fmtNumber(d.weekly_goal) })
      : '',
    bucket === 'day' && s.days_over_reference !== null && s.buckets_complete > 0
      ? t('points.summary.dayRef', { over: fmtNumber(s.days_over_reference), total: fmtNumber(s.buckets_complete), ref: fmtNumber(ref) })
      : '',
    weekly && pts.some((x) => !x.complete) ? t('points.summary.partial') : '',
    bucket === 'day' && pts.some((x) => !x.complete) ? t('points.summary.partialDay') : '',
    d.coarsened ? t('points.summary.coarsened') : '',
    t('points.summary.prev', { total: fmtNumber(d.previous_summary.total) }),
    d.hr_configured ? '' : t('points.warn.noHrMax'),
  ]
  const target = weekly ? d.weekly_goal : d.daily_reference
  const hasTarget = weekly || bucket === 'day'
  const goalCell = (x: PointsSeriesResponse['points'][number]) =>
    !hasTarget ? [] : [x.complete ? t(x.v >= target ? 'points.col.yes' : 'points.col.no') : t('points.col.running')]
  const columns = [t('chart.col.when'), `${label} (${t('points.unit')})`, ...(weekly ? [t('points.col.goal', { goal: fmtNumber(d.weekly_goal) })] : bucket === 'day' ? [t('points.col.reference', { ref: fmtNumber(ref) })] : [])]
  const table: TableSpec = {
    caption: t('chart.tableCaption', { label, bucket: t(`points.bucket.${bucket}` as const) }),
    columns,
    rows: pts.map((x) => [bucketLong(x.t, bucket), fmtNumber(x.v), ...goalCell(x)]),
  }
  const csv = {
    filename: csvName('punti_cardio', d.from, d.to, bucket),
    columns: [t('chart.col.date'), `${label} (${t('points.unit')})`, t('points.col.days'), ...(weekly ? [t('points.col.goalReached')] : bucket === 'day' ? [t('points.col.refReached')] : [])],
    rows: pts.map((x) => [x.t, x.v, x.days, ...(hasTarget ? [x.complete ? (x.v >= target ? 'si' : 'no') : 'in_corso'] : [])]),
  }
  return {
    option,
    table,
    csv,
    summary: parts.filter(Boolean).join(' '),
    readout: (i: number) => {
      const x = pts[i]
      return x ? `${bucketLong(x.t, bucket)} · ${fmtNumber(x.v)} ${t('points.unit')}` : ''
    },
  }
}

export function HeartPointsChart({ range }: { range: ResolvedRange }) {
  const reduced = useReducedMotion() ?? false
  const [chosen, setChosen] = useState<PointsBucket | null>(null)
  const bucket = chosen ?? defaultPointsBucket(range.days)
  const [cursor, setCursor] = useState<number | null>(null)
  const id = useId()
  const q = useQuery(pointsSeriesQuery({ from: range.from, to: range.to, bucket }))
  const built = useMemo(() => (q.data ? buildChart(q.data, reduced) : null), [q.data, reduced])
  return (
    <Panel title={t('points.title')} icon={Lightning} accent="heart" testId="chart-heartpoints">
      <Async
        query={q}
        skeleton={<Skeleton className="h-[260px] w-full" label={t('state.loading')} />}
        isEmpty={(d) => d.summary.days === 0}
        emptyTitle={t('points.empty.title')}
        emptyHint={t('points.empty.hint')}
      >
        {(d) =>
          built && (
            <ChartFrame
              summary={built.summary}
              option={built.option}
              table={built.table}
              csv={built.csv}
              height={260}
              controls={
                <div className="flex flex-wrap items-center gap-3 no-print" data-testid="points-controls">
                  <label htmlFor={id} className="hud-label">
                    {t('chart.granularity')}
                  </label>
                  <select
                    id={id}
                    className="input w-auto"
                    value={bucket}
                    onChange={(e) => {
                      setChosen(e.target.value as PointsBucket)
                      setCursor(null)
                    }}
                  >
                    {BUCKETS.map((b) => (
                      <option key={b} value={b}>
                        {t(`points.bucket.${b}.opt` as const)}
                      </option>
                    ))}
                  </select>
                  {!d.hr_configured && <HrMaxWarning />}
                </div>
              }
              cursor={{
                count: d.points.length,
                index: cursor,
                onChange: setCursor,
                readout: cursor === null ? '' : built.readout(cursor),
              }}
              note={
                <p className="text-xs text-fg-muted" data-testid="points-chart-note">
                  {t('points.chart.note', { goal: fmtNumber(d.weekly_goal) })}
                </p>
              }
            />
          )
        }
      </Async>
    </Panel>
  )
}

// --------------------------------------------------------------------------- rules

export function PointsRulesPanel() {
  const q = useQuery(pointsRulesQuery())
  return (
    <section
      id="points-rules"
      tabIndex={-1}
      className="hud-panel flex min-w-0 flex-col gap-3 outline-none"
      aria-labelledby="points-rules-title"
      data-testid="points-rules"
    >
      <h2 id="points-rules-title" className="hud-label flex items-center gap-2">
        <ListChecks size={18} aria-hidden />
        {t('points.rules.title')}
      </h2>
      <Async query={q} skeleton={<Skeleton className="h-24 w-full" />}>
        {(r) => <RulesBody r={r} />}
      </Async>
    </section>
  )
}

function RulesBody({ r }: { r: PointsRules }) {
  const hr = r.heart_rate
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className="text-fg-muted">{t('points.rules.intro')}</p>
      <ul className="list-disc space-y-1 pl-5" data-testid="points-rules-list">
        <li data-rule="heart_rate">
          {t('points.rules.hr', {
            m: fmtNumber(hr.moderate_pct),
            v: fmtNumber(hr.vigorous_pct),
            pm: fmtNumber(r.points.moderate),
            pv: fmtNumber(r.points.vigorous),
          })}
        </li>
        <li data-rule="cadence">
          {t('points.rules.cadence', {
            m: fmtNumber(r.cadence.moderate_steps),
            v: fmtNumber(r.cadence.vigorous_steps),
            pm: fmtNumber(r.points.moderate),
            pv: fmtNumber(r.points.vigorous),
            mx: fmtNumber(r.cadence.max_record_minutes),
          })}
        </li>
        <li data-rule="combine">{t('points.rules.max')}</li>
        <li data-rule="hr_max" data-configured={hr.configured}>
          {hr.configured && hr.hr_max !== null
            ? t(hr.hr_max_source === 'override' ? 'points.rules.hrMax.override' : 'points.rules.hrMax.birth', {
                value: fmtNumber(hr.hr_max),
                moderate: fmtNumber(Math.ceil((hr.hr_max * hr.moderate_pct) / 100)),
                vigorous: fmtNumber(Math.ceil((hr.hr_max * hr.vigorous_pct) / 100)),
              })
            : t('points.warn.noHrMax')}
        </li>
        <li data-rule="carry">{t('points.rules.carry', { n: fmtNumber(hr.carry_max_minutes) })}</li>
        <li data-rule="met" data-met-used={r.met_used}>
          {t('points.rules.met')}
        </li>
        <li data-rule="all">{t('points.rules.all')}</li>
        <li data-rule="daily_reference">
          {t('points.rules.dayRef', { goal: fmtNumber(r.weekly_goal), ref: fmtNumber(Math.round(r.daily_reference)) })}
        </li>
        <li data-rule="goal">
          {t('points.rules.goal', { goal: fmtNumber(r.weekly_goal), tz: r.timezone.split('/').pop() ?? r.timezone })}
        </li>
      </ul>
    </div>
  )
}
