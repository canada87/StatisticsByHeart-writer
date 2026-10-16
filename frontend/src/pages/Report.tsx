import { CaretLeft, CaretRight, DownloadSimple, Printer } from '@phosphor-icons/react'
import * as ToggleGroup from '@radix-ui/react-toggle-group'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useId, useState } from 'react'
import { reportDailyQuery, reportQuery } from '../api/queries'
import type { ReportMetric, ReportResponse } from '../api/types'
import { DeltaBadge } from '../components/Kpi'
import { Sparkline } from '../components/gauges'
import { PageTitle, Panel } from '../components/hud'
import { Async, EmptyState, ErrorState, SkeletonLines } from '../components/states'
import { type MessageKey, t } from '../i18n'
import { csvName, downloadCsv, toCsv } from '../lib/csv'
import { describeDelta } from '../lib/delta'
import { fmtDay, fmtDayLong, fmtDateTime, fmtDuration, fmtNumber, todayLocal } from '../lib/format'
import { type MetricDef, METRICS, fmtMetric } from '../lib/metrics'
import {
  PERIOD_KINDS,
  type Period,
  type PeriodKind,
  canGoNext,
  parsePeriodSearch,
  resolvePeriod,
  shiftAnchor,
} from '../lib/period'
import { activityLabel } from '../components/DomainCharts'

const BY_KEY: Record<string, MetricDef> = Object.fromEntries(Object.values(METRICS).map((m) => [m.reportKey, m]))
const ROW_ORDER = [
  'steps',
  'distance',
  'active_kcal',
  'total_kcal',
  'heart_rate',
  'resting_hr',
  'hrv',
  'spo2',
  'sleep',
  'workouts',
  'weight',
  'blood_pressure',
] as const
const LABEL: Record<string, MessageKey> = {
  steps: 'm.steps',
  distance: 'm.distance',
  active_kcal: 'm.activeKcal',
  total_kcal: 'm.totalKcal',
  heart_rate: 'm.heartRate',
  resting_hr: 'm.restingHr',
  hrv: 'm.hrv',
  spo2: 'm.spo2',
  sleep: 'm.sleep',
  workouts: 'm.workouts',
  weight: 'm.weight',
  blood_pressure: 'm.bloodPressure',
}
const monthFmt = new Intl.DateTimeFormat('it-IT', { timeZone: 'UTC', month: 'long', year: 'numeric' })

export function periodLabel(p: Period): string {
  if (p.kind === 'month') return monthFmt.format(new Date(`${p.start}T00:00:00Z`))
  if (p.kind === 'year') return p.start.slice(0, 4)
  const range = `${fmtDayLong(p.start)} – ${fmtDayLong(p.end)}`
  return p.kind === 'week' ? `${t('period.week')} ${range}` : range
}

// --------------------------------------------------------------------------- controls

function PeriodControls({ period }: { period: Period }) {
  const navigate = useNavigate()
  const fromId = useId()
  const toId = useId()
  const today = todayLocal()
  const set = (next: Record<string, string | undefined>) =>
    void navigate({
      to: '.',
      search: ((prev: Record<string, unknown>) => ({
        ...prev,
        p: undefined,
        d: undefined,
        from: undefined,
        to: undefined,
        ...next,
      })) as never,
    })
  return (
    <div className="flex flex-wrap items-center gap-3 no-print" data-testid="period-controls">
      <ToggleGroup.Root
        type="single"
        value={period.kind}
        onValueChange={(v) => {
          if (!v) return
          const kind = v as PeriodKind
          if (kind === 'custom') set({ p: 'custom', from: period.start, to: period.last })
          else set({ p: kind === 'week' ? undefined : kind, d: period.anchor })
        }}
        aria-label={t('period.label')}
        className="inline-flex border border-border-control"
      >
        {PERIOD_KINDS.map((k) => (
          <ToggleGroup.Item
            key={k}
            value={k}
            aria-label={k === 'custom' ? t('period.custom.aria') : undefined}
            className="min-h-11 border-r border-border-control px-2.5 font-display text-sm uppercase tracking-wider last:border-r-0 sm:px-3 hover:bg-accent-glow/10 data-[state=on]:bg-accent data-[state=on]:text-black data-[state=on]:hover:bg-accent"
          >
            {k === 'custom' ? t('period.custom.short') : t(`period.${k}` as MessageKey)}
          </ToggleGroup.Item>
        ))}
      </ToggleGroup.Root>
      {period.kind !== 'custom' ? (
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="btn px-2"
            aria-label={t('period.prev')}
            onClick={() => set({ p: period.kind === 'week' ? undefined : period.kind, d: shiftAnchor(period, -1) })}
          >
            <CaretLeft size={20} aria-hidden />
          </button>
          <button
            type="button"
            className="btn px-2"
            aria-label={t('period.next')}
            disabled={!canGoNext(period)}
            onClick={() => set({ p: period.kind === 'week' ? undefined : period.kind, d: shiftAnchor(period, 1) })}
          >
            <CaretRight size={20} aria-hidden />
          </button>
          <button type="button" className="btn" onClick={() => set({ p: period.kind === 'week' ? undefined : period.kind })}>
            {t('period.current')}
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={fromId} className="hud-label">
            {t('range.from')}
          </label>
          <input id={fromId} type="date" className="input w-auto" value={period.start} max={period.last} onChange={(e) => e.target.value && set({ p: 'custom', from: e.target.value, to: period.last })} />
          <label htmlFor={toId} className="hud-label">
            {t('range.to')}
          </label>
          <input id={toId} type="date" className="input w-auto" value={period.last} min={period.start} max={today} onChange={(e) => e.target.value && set({ p: 'custom', from: period.start, to: e.target.value })} />
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- summary table

function dayText(def: MetricDef | undefined, d: { date: string; value: number } | null): string {
  if (!d) return '—'
  return `${fmtDay(d.date)} · ${def ? fmtMetric(def, d.value) : fmtNumber(d.value, 1)}`
}

function MetricRow({ m, report }: { m: ReportMetric; report: ReportResponse }) {
  const def = BY_KEY[m.key]
  const label = t(LABEL[m.key] ?? 'm.steps')
  const empty = m.days_with_data === 0
  const cells: { avg: string; total: string; range: string } = (() => {
    if (empty) return { avg: '—', total: '—', range: '—' }
    if (m.key === 'workouts') {
      const w = report.workouts
      return {
        avg: w.avg_duration_s === null ? '—' : `${fmtDuration(w.avg_duration_s)} ${t('report.perWorkout')}`,
        total: `${fmtNumber(w.count)} · ${fmtDuration(w.duration_s)}`,
        range: '—',
      }
    }
    if (m.key === 'blood_pressure' && def) {
      const d = m.diastolic
      return {
        avg: `${fmtMetric(def, m.current.avg)}/${fmtNumber(d?.avg ?? null, 0)}`,
        total: '—',
        range: `${fmtMetric(def, m.current.min)}–${fmtMetric(def, m.current.max)}`,
      }
    }
    if (m.key === 'sleep') {
      return { avg: fmtDuration(m.current.avg), total: fmtDuration(m.current.total), range: `${fmtDuration(m.current.min)} – ${fmtDuration(m.current.max)}` }
    }
    if (!def) return { avg: '—', total: '—', range: '—' }
    return {
      avg: fmtMetric(def, m.current.avg),
      total: m.current.total === null ? '—' : fmtMetric(def, m.current.total),
      range: `${fmtMetric(def, m.current.min)} – ${fmtMetric(def, m.current.max)}`,
    }
  })()
  const unit = m.key === 'sleep' || m.key === 'workouts' ? '' : def?.unit ? ` ${def.unit}` : ''
  const delta = describeDelta(
    m.kind === 'sum' ? m.current.total : m.current.avg,
    m.kind === 'sum' ? m.previous.total : m.previous.avg,
  )
  return (
    <tr className="border-t border-border align-top" data-testid={`report-row-${m.key}`}>
      <th scope="row" className="min-w-28 px-2 py-2 text-left font-normal">
        {label}
        {!empty && <span className="block text-xs text-fg-muted">{t('kpi.days.short', { n: m.days_with_data, prev: fmtNumber(m.previous.days) })}</span>}
      </th>
      <td className="whitespace-nowrap px-2 py-2 print:whitespace-normal">{empty ? t('kpi.noData') : `${cells.avg}${m.key === 'blood_pressure' ? ' mmHg' : cells.avg === '—' ? '' : unit}`}</td>
      <td className="whitespace-nowrap px-2 py-2 print:whitespace-normal">{cells.total === '—' ? '—' : `${cells.total}${m.key === 'workouts' ? '' : unit}`}</td>
      <td className="whitespace-nowrap px-2 py-2 print:whitespace-normal">{cells.range}</td>
      <td className="whitespace-nowrap px-2 py-2 print:whitespace-normal">{empty ? '—' : <DeltaBadge delta={delta} compact />}</td>
      <td className="px-2 py-2 text-xs">
        {m.higher_is_better === null || empty ? (
          '—'
        ) : (
          <>
            <span className="block whitespace-nowrap print:whitespace-normal">
              <span className="text-fg-muted">{t('report.best')}</span> {dayText(def, m.best_day)}
            </span>
            <span className="block whitespace-nowrap print:whitespace-normal">
              <span className="text-fg-muted">{t('report.worst')}</span> {dayText(def, m.worst_day)}
            </span>
          </>
        )}
      </td>
      <td className="px-2 py-2 text-accent-glow">
        {empty ? null : (
          <span role="img" aria-label={t('report.sparkAlt', { label, bucket: t(`bucket.${m.spark_bucket}` as MessageKey) })}>
            <Sparkline values={m.spark} width={96} height={28} color="currentColor" />
          </span>
        )}
      </td>
    </tr>
  )
}

function ReportBody({ report, period }: { report: ReportResponse; period: Period }) {
  const byKey = new Map(report.metrics.map((m) => [m.key, m]))
  const sleep = report.sleep_regularity
  const w = report.workouts
  const allEmpty = report.metrics.every((m) => m.days_with_data === 0)
  if (allEmpty) return <EmptyState title={t('report.empty')} hint={t('report.emptyHint')} />
  return (
    <div className="flex flex-col gap-3">
      <Panel title={t('report.summary')} accent="glow" testId="report-summary">
        <p className="text-sm text-fg-muted">
          {t('report.compared', { from: fmtDayLong(report.previous_from), to: fmtDayLong(report.previous_to) })}
        </p>
        <p className="text-sm text-fg-muted" data-testid="report-workouts-note">
          {t('report.workoutsRealNote')}
        </p>
        <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={t('report.summary')}>
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">{t('report.summary')}</caption>
            <thead className="bg-surface-muted">
              <tr>
                {(['report.col.metric', 'report.col.avg', 'report.col.total', 'report.col.range', 'report.col.delta', 'report.col.days', 'report.col.trend'] as const).map((k) => (
                  <th key={k} scope="col" className="px-2 py-1.5 text-left font-normal text-fg-muted">
                    {t(k)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROW_ORDER.map((k) => {
                const m = byKey.get(k)
                return m ? <MetricRow key={k} m={m} report={report} /> : null
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="grid gap-3 md:grid-cols-2 print-avoid-break">
        <Panel title={t('report.sleepBlock')} accent="sleep" testId="report-sleep">
          {sleep && sleep.nights > 0 ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-fg-muted">{t('sleep.nights', { n: sleep.nights })}</dt>
              <dd>{fmtDuration(sleep.avg_asleep_s)} {t('kpi.avgNight')}</dd>
              <dt className="text-fg-muted">{t('sleep.bedtime.avg')}</dt>
              <dd>{clockText(sleep.bedtime_avg_min, 18)} (±{fmtNumber(sleep.bedtime_sd_min, 0)} min)</dd>
              <dt className="text-fg-muted">{t('sleep.wake.avg')}</dt>
              <dd>{clockText(sleep.wake_avg_min, 0)} (±{fmtNumber(sleep.wake_sd_min, 0)} min)</dd>
            </dl>
          ) : (
            <EmptyState title={t('sleep.stages.empty')} />
          )}
        </Panel>
        <Panel title={t('report.workoutsBlock')} accent="activity" testId="report-workouts">
          {w.count > 0 ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-fg-muted">{t('workouts.count')}</dt>
              <dd>{fmtNumber(w.count)} ({fmtNumber(w.per_week, 1)} {t('report.perWeek')})</dd>
              <dt className="text-fg-muted">{t('workouts.col.duration')}</dt>
              <dd>{fmtDuration(w.duration_s)} · {t('workouts.avgDuration')} {fmtDuration(w.avg_duration_s)}</dd>
              <dt className="text-fg-muted">{t('workouts.byType')}</dt>
              <dd>{Object.entries(w.by_type).map(([k, n]) => `${activityLabel(k)} ${n}`).join(', ')}</dd>
            </dl>
          ) : (
            <EmptyState title={t('workouts.none')} />
          )}
          {w.excluded > 0 && (
            <p className="mt-2 text-xs text-fg-muted" data-testid="report-workouts-excluded">
              {t('report.workoutsReal', { n: w.excluded })}
            </p>
          )}
        </Panel>
      </div>
      <p className="text-xs text-fg-muted print-avoid-break">
        {t('report.footer', { generated: fmtDateTime(report.generated_at), days: period.days })}
      </p>
    </div>
  )
}

function clockText(min: number | null, origin: 0 | 18): string {
  if (min === null) return '—'
  const m = (((origin * 60 + Math.round(min)) % 1440) + 1440) % 1440
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

// --------------------------------------------------------------------------- page

export function ReportPage() {
  const raw = useSearch({ strict: false }) as Record<string, unknown>
  const period = resolvePeriod(parsePeriodSearch(raw))
  const window = { from: period.start, to: period.last }
  const q = useQuery({ ...reportQuery(window), enabled: period.days > 0 })
  const queryClient = useQueryClient()
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<unknown>(null)

  const exportCsv = async () => {
    setExporting(true)
    setExportError(null)
    try {
      const daily = await queryClient.fetchQuery(reportDailyQuery(window))
      const cols = daily.columns
      downloadCsv(
        csvName('report', period.start, period.last),
        toCsv(
          ['data', ...cols.map((c) => c.key)],
          daily.rows.map((r) => [r.date, ...cols.map((c) => r.values[c.key] ?? null)]),
        ),
      )
    } catch (err) {
      setExportError(err)
    } finally {
      setExporting(false)
    }
  }

  return (
    <div>
      <div className="print-only mb-2 text-xs">StatisticsByHeart · {t('report.title')}</div>
      <PageTitle sub={<span data-testid="period-label">{periodLabel(period)}</span>}>{t('report.title')}</PageTitle>
      <div className="mb-3 flex flex-col gap-3 no-print">
        <PeriodControls period={period} />
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn btn-primary" onClick={() => window_print()} data-testid="print-button">
            <Printer size={20} aria-hidden />
            {t('report.print')}
          </button>
          <button type="button" className="btn" onClick={() => void exportCsv()} disabled={exporting}>
            <DownloadSimple size={20} aria-hidden />
            {exporting ? t('report.exporting') : t('report.exportCsv')}
          </button>
        </div>
        {exportError !== null && <ErrorState error={exportError} onRetry={() => void exportCsv()} />}
      </div>
      <Async query={q} skeleton={<SkeletonLines lines={8} height="h-9" />}>
        {(report) => <ReportBody report={report} period={period} />}
      </Async>
    </div>
  )
}

function window_print() {
  globalThis.print()
}
