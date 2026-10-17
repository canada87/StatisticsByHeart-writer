import { CalendarBlank, Lightning } from '@phosphor-icons/react'
import { Link } from '@tanstack/react-router'
import type { Bucket, ReportMonthly, ReportResponse } from '../api/types'
import { type MessageKey, t } from '../i18n'
import { fmtDay, fmtDuration, fmtNumber } from '../lib/format'
import { METRICS } from '../lib/metrics'
import type { Period } from '../lib/period'
import type { ResolvedRange } from '../lib/range'
import { activityLabel } from './DomainCharts'
import { HeartPointsChart, HrMaxWarning } from './HeartPoints'
import { Panel } from './hud'
import { TrendChart } from './TrendChart'

const monthFmt = new Intl.DateTimeFormat('it-IT', { timeZone: 'UTC', month: 'short', year: 'numeric' })

export function monthText(day: string): string {
  return monthFmt.format(new Date(`${day}T00:00:00Z`))
}

const COLUMN_LABEL: Record<string, MessageKey> = {
  heart_rate: 'm.heartRate',
  hr_day: 'm.hrDay',
  hr_night: 'm.hrNight',
  resting_hr: 'm.restingHr',
  hrv: 'm.hrv',
  spo2: 'm.spo2',
  sleep: 'm.sleepPerNight',
  sleep_nights: 'm.sleepNights',
  weight: 'm.weight',
  systolic: 'm.systolic',
  diastolic: 'm.diastolic',
  steps: 'm.steps',
  distance: 'm.distance',
  active_kcal: 'm.activeKcal',
  total_kcal: 'm.totalKcal',
  heart_points: 'm.heartPoints',
  workouts: 'report.monthly.workoutsCount',
  workouts_s: 'report.monthly.workoutsTime',
}

/** Compact header unit (the number cells then carry no unit). */
const COLUMN_UNIT: Record<string, string> = {
  heart_rate: 'bpm',
  hr_day: 'bpm',
  hr_night: 'bpm',
  resting_hr: 'bpm',
  hrv: 'ms',
  spo2: '%',
  sleep: 'h min',
  sleep_nights: 'n',
  weight: 'kg',
  systolic: 'mmHg',
  diastolic: 'mmHg',
  steps: '',
  distance: 'km',
  active_kcal: 'kcal',
  total_kcal: 'kcal',
  heart_points: 'punti',
  workouts: 'n',
  workouts_s: 'h min',
}

export function fmtMonthly(key: string, v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  switch (key) {
    case 'sleep':
    case 'workouts_s':
      return fmtDuration(v)
    case 'distance':
      return fmtNumber(v / 1000, 1)
    case 'weight':
    case 'spo2':
      return fmtNumber(v, 1)
    default:
      return fmtNumber(v, 0)
  }
}

function MonthTable({ title, keys, monthly, id }: { title: string; keys: string[]; monthly: ReportMonthly; id: string }) {
  return (
    <div className="flex flex-col gap-1 report-monthly" data-testid={`monthly-${id}`}>
      <h3 className="text-sm text-fg-muted">{title}</h3>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={title}>
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">{title}</caption>
          <thead className="bg-surface-muted">
            <tr>
              <th scope="col" className="px-2 py-1.5 text-left font-normal text-fg-muted">
                {t('report.monthly.month')}
              </th>
              {keys.map((k) => (
                <th key={k} scope="col" className="px-2 py-1.5 text-right font-normal text-fg-muted" data-col={k}>
                  {t(COLUMN_LABEL[k] ?? 'm.steps')}
                  {COLUMN_UNIT[k] ? <span className="block text-xs">{COLUMN_UNIT[k]}</span> : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {monthly.months.map((m) => (
              <tr key={m.month} className="border-t border-border" data-testid="month-row" data-partial={m.partial}>
                <th scope="row" className="whitespace-nowrap px-2 py-1.5 text-left font-normal print:whitespace-normal">
                  {monthText(m.month)}
                  {m.partial && (
                    <span className="block text-xs text-fg-muted" data-testid="month-partial">
                      {t('report.monthly.partial', { n: fmtNumber(m.days) })}
                    </span>
                  )}
                </th>
                {keys.map((k) => (
                  <td key={k} className="whitespace-nowrap px-2 py-1.5 text-right print:whitespace-normal">
                    {fmtMonthly(k, m.values[k])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Month by month over the whole period: daily means of the month, then the month totals. */
export function MonthlyTables({ report, period }: { report: ReportResponse; period: Period }) {
  const monthly = report.monthly
  // one whole week inside one month would only repeat the summary table above
  if (monthly.months.length === 0 || (monthly.months.length === 1 && period.kind === 'week')) return null
  const avgKeys = monthly.columns.filter((c) => c.kind === 'avg' && monthly.months.some((m) => m.values[c.key] !== null)).map((c) => c.key)
  const sumKeys = monthly.columns.filter((c) => c.kind === 'sum' && monthly.months.some((m) => m.values[c.key] !== null)).map((c) => c.key)
  return (
    <Panel title={t('report.monthly.title')} icon={CalendarBlank} accent="glow" testId="report-monthly">
      <p className="text-sm text-fg-muted">{t('report.monthly.intro')}</p>
      {avgKeys.length > 0 && <MonthTable id="avg" title={t('report.monthly.avgTitle')} keys={avgKeys} monthly={monthly} />}
      {sumKeys.length > 0 && <MonthTable id="sum" title={t('report.monthly.sumTitle')} keys={sumKeys} monthly={monthly} />}
      {monthly.months.some((m) => m.partial) && <p className="text-xs text-fg-muted">{t('report.monthly.partialNote')}</p>}
    </Panel>
  )
}

/** Heart Points of the period: total, weekly mean and weeks above the goal. */
export function PointsBlock({ report }: { report: ReportResponse }) {
  const p = report.points
  return (
    <Panel title={t('report.pointsBlock')} icon={Lightning} accent="heart" testId="report-points">
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-fg-muted">{t('report.points.total')}</dt>
        <dd data-testid="report-points-total">{fmtNumber(p.total)} {t('points.unit')}</dd>
        <dt className="text-fg-muted">{t('report.points.weekly')}</dt>
        <dd data-testid="report-points-weekly">{p.weekly_avg === null ? '—' : `${fmtNumber(p.weekly_avg, 0)} ${t('points.unit')}`}</dd>
        <dt className="text-fg-muted">{t('report.points.goal', { goal: fmtNumber(p.goal) })}</dt>
        <dd data-testid="report-points-goal">
          {p.weeks_complete > 0
            ? t('report.points.weeksOver', { over: fmtNumber(p.weeks_over_goal), total: fmtNumber(p.weeks_complete) })
            : t('report.points.noWeeks')}
        </dd>
        <dt className="text-fg-muted">{t('report.points.previous')}</dt>
        <dd>{fmtNumber(p.previous_total)} {t('points.unit')}</dd>
      </dl>
      {!p.hr_configured && <HrMaxWarning />}
    </Panel>
  )
}

/** Real workouts only: how many and how long, per type. */
export function WorkoutTypes({ report }: { report: ReportResponse }) {
  const w = report.workouts
  if (w.by_type_detail.length === 0) return null
  return (
    <div className="mt-2" data-testid="report-workout-types">
      <h3 className="text-xs text-fg-muted">{t('report.workouts.byType')}</h3>
      <table className="mt-1 w-full border-collapse text-sm">
        <caption className="sr-only">{t('report.workouts.byType')}</caption>
        <thead>
          <tr className="text-left text-xs text-fg-muted">
            <th scope="col" className="py-1 font-normal">{t('workouts.col.type')}</th>
            <th scope="col" className="py-1 text-right font-normal">{t('report.monthly.workoutsCount')}</th>
            <th scope="col" className="py-1 text-right font-normal">{t('workouts.col.duration')}</th>
          </tr>
        </thead>
        <tbody>
          {w.by_type_detail.map((d) => (
            <tr key={d.type} className="border-t border-border" data-testid="workout-type-row">
              <th scope="row" className="py-1 text-left font-normal">{activityLabel(d.type)}</th>
              <td className="py-1 text-right">{fmtNumber(d.count)}</td>
              <td className="py-1 text-right">{fmtDuration(d.duration_s)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function WorkoutsRulesNote() {
  return (
    <p className="mt-2 text-xs text-fg-muted" data-testid="report-workouts-rules">
      {t('report.workouts.rules')}{' '}
      <Link to="/activity" hash="workout-rules" search={((prev: Record<string, unknown>) => prev) as never} className="underline no-print">
        {t('workouts.rules.link')}
      </Link>
    </p>
  )
}

/** Big charts of the period, one per row; the PDF is the priority (full A4 width, tall, no cuts). */
export function ReportCharts({ report, period }: { report: ReportResponse; period: Period }) {
  const M = METRICS
  const range: ResolvedRange = { preset: 'custom', from: period.start, to: period.last, days: period.days, current: true }
  const months = report.monthly.months.length
  // a period over several months reads best per month
  const bucket: Bucket | undefined = months >= 3 ? 'month' : undefined
  const has = (key: string) => (report.metrics.find((m) => m.key === key)?.days_with_data ?? 0) > 0
  const common = { range, height: 340, defaultBucket: bucket, perDay: true } as const
  return (
    <section className="flex flex-col gap-3" aria-labelledby="report-charts-title" data-testid="report-charts">
      <h2 id="report-charts-title" className="hud-label">
        {t('report.charts')}
      </h2>
      <p className="text-xs text-fg-muted">{t(months >= 3 ? 'report.charts.monthly' : 'report.charts.intro')}</p>
      {has('steps') && (
        <div className="report-chart">
          <TrendChart def={M.steps} icon={CalendarBlank} accent="activity" {...common} />
        </div>
      )}
      {has('heart_rate') && (
        <div className="report-chart">
          <TrendChart def={M.heartRate} daypart icon={Lightning} accent="heart" {...common} />
        </div>
      )}
      {has('resting_hr') && (
        <div className="report-chart">
          <TrendChart def={M.restingHr} icon={Lightning} accent="heart" {...common} />
        </div>
      )}
      {has('hrv') && (
        <div className="report-chart">
          <TrendChart def={M.hrv} icon={Lightning} accent="vitals" {...common} />
        </div>
      )}
      {has('spo2') && (
        <div className="report-chart">
          <TrendChart def={M.spo2} icon={Lightning} accent="vitals" {...common} />
        </div>
      )}
      {has('sleep') && (
        <div className="report-chart">
          <TrendChart def={M.sleep} icon={Lightning} accent="sleep" {...common} />
        </div>
      )}
      {has('weight') && (
        <div className="report-chart">
          <TrendChart def={M.weight} icon={Lightning} accent="glow" {...common} />
        </div>
      )}
      {has('blood_pressure') && (
        <div className="report-chart">
          <TrendChart def={M.systolic} pair={M.diastolic} icon={Lightning} accent="heart" {...common} />
        </div>
      )}
      {report.points.total > 0 && (
        <div className="report-chart">
          <HeartPointsChart range={range} height={340} initialBucket={months >= 3 ? 'month' : undefined} />
        </div>
      )}
    </section>
  )
}

export { fmtDay }
