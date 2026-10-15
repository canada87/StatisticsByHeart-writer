import { Clock, DownloadSimple, Moon, PersonSimpleRun } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useReducedMotion } from 'motion/react'
import { useMemo, useState } from 'react'
import { exerciseQuery, sleepNightsQuery } from '../api/queries'
import type { ExerciseResponse, ExerciseRow, SleepNight } from '../api/types'
import { type MessageKey, t } from '../i18n'
import { baseOption, palette } from '../lib/charts'
import { csvName, downloadCsv, toCsv } from '../lib/csv'
import { fmtDateTime, fmtDay, fmtDayShort, fmtDuration, fmtNumber } from '../lib/format'
import type { ResolvedRange } from '../lib/range'
import { ChartFrame } from './ChartCard'
import { Panel } from './hud'
import { Async, EmptyState, Skeleton } from './states'

const skeleton = <Skeleton className="h-[260px] w-full" />

function rgba(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

export function clock(minAfter18: number): string {
  const m = (((1080 + Math.round(minAfter18)) % 1440) + 1440) % 1440
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
}

// --------------------------------------------------------------------------- sleep stages

const STAGES = ['deep', 'rem', 'light', 'sleeping', 'awake', 'awake_in_bed', 'out_of_bed', 'unknown'] as const
const STAGE_ALPHA: Record<string, number> = { deep: 1, rem: 0.75, light: 0.5, sleeping: 0.6 }

export function SleepStagesChart({ range }: { range: ResolvedRange }) {
  const q = useQuery(sleepNightsQuery({ from: range.from, to: range.to }))
  const reduced = useReducedMotion() ?? false
  const [cursor, setCursor] = useState<number | null>(null)

  const built = useMemo(() => {
    const nights = q.data?.nights.filter((n) => Object.keys(n.stages_s).length > 0)
    if (!nights?.length) return null
    const p = palette()
    const present = STAGES.filter((k) => nights.some((n) => (n.stages_s[k] ?? 0) > 0))
    const h = (s: number | undefined) => Math.round(((s ?? 0) / 3600) * 100) / 100
    const option = baseOption(
      nights.map((n) => fmtDayShort(n.date)),
      [],
      { unit: 'h', showLegend: true, reducedMotion: reduced },
    ) as Record<string, unknown>
    option.series = present.map((k) => ({
      name: t(`stage.${k}` as MessageKey),
      type: 'bar',
      stack: 'night',
      data: nights.map((n) => h(n.stages_s[k])),
      barMaxWidth: 28,
      itemStyle: { color: k === 'awake' || k === 'awake_in_bed' || k === 'out_of_bed' ? p.muted : rgba(p.sleep, STAGE_ALPHA[k] ?? 0.3) },
    }))
    // Decal patterns tell the stages apart without relying on the colour.
    option.aria = { enabled: true, decal: { show: true } }
    const avg = (k: string) => nights.reduce((s, n) => s + (n.stages_s[k] ?? 0), 0) / nights.length
    const summary = t('sleep.stages.summary', {
      count: nights.length,
      deep: fmtDuration(avg('deep')),
      rem: fmtDuration(avg('rem')),
      light: fmtDuration(avg('light')),
    })
    const cols = [t('chart.col.date'), ...present.map((k) => t(`stage.${k}` as MessageKey))]
    const csvRows = nights.map((n) => [n.date, ...present.map((k) => Math.round(n.stages_s[k] ?? 0))])
    return {
      option,
      summary,
      nights,
      present,
      table: {
        caption: t('sleep.stages.caption'),
        columns: [t('chart.col.when'), ...cols.slice(1)],
        rows: nights.map((n) => [fmtDay(n.date), ...present.map((k) => fmtDuration(n.stages_s[k] ?? 0))]),
      },
      csv: { filename: csvName('sonno-stadi', range.from, range.to), columns: [cols[0] ?? '', ...cols.slice(1).map((c) => `${c} (s)`)], rows: csvRows },
      readout: (i: number) => {
        const n = nights[i]
        return n ? [fmtDay(n.date), ...present.map((k) => `${t(`stage.${k}` as MessageKey)} ${fmtDuration(n.stages_s[k] ?? 0)}`)].join(' · ') : ''
      },
    }
  }, [q.data, range.from, range.to, reduced])

  return (
    <Panel title={t('sleep.stages.title')} icon={Moon} accent="sleep" testId="chart-sleep-stages">
      <Async
        query={q}
        skeleton={skeleton}
        isEmpty={() => !built}
        emptyTitle={t('sleep.stages.empty')}
        emptyHint={t('chart.empty.hint')}
      >
        {() =>
          built && (
            <ChartFrame
              summary={built.summary}
              option={built.option}
              table={built.table}
              csv={built.csv}
              cursor={{ count: built.nights.length, index: cursor, onChange: setCursor, readout: cursor === null ? '' : built.readout(cursor) }}
            />
          )
        }
      </Async>
    </Panel>
  )
}

// --------------------------------------------------------------------------- sleep schedule

export function SleepScheduleChart({ range }: { range: ResolvedRange }) {
  const q = useQuery(sleepNightsQuery({ from: range.from, to: range.to }))
  const reduced = useReducedMotion() ?? false
  const [cursor, setCursor] = useState<number | null>(null)

  const built = useMemo(() => {
    const nights = q.data?.nights.filter((n) => n.bedtime_min !== null && n.wake_min !== null)
    if (!nights?.length) return null
    const p = palette()
    // one axis, minutes after 18:00: wake-up (after midnight) sits 360 min above its own clock value
    const bed = nights.map((n) => n.bedtime_min as number)
    const wake = nights.map((n) => 360 + (n.wake_min as number))
    const option = baseOption(
      nights.map((n) => fmtDayShort(n.date)),
      [
        { name: t('sleep.bedtime'), color: p.sleep, kind: 'line', dashed: true, data: bed, short: t('sleep.bedtime.short') },
        { name: t('sleep.wake'), color: p.glow, kind: 'line', data: wake, short: t('sleep.wake.short') },
      ],
      { showLegend: true, reducedMotion: reduced, endLabels: true },
    ) as Record<string, unknown> & { yAxis: Record<string, unknown>; tooltip: Record<string, unknown> }
    option.yAxis = { ...option.yAxis, axisLabel: { color: p.muted, formatter: (v: number) => clock(v) }, interval: 120, scale: true }
    option.tooltip = {
      ...option.tooltip,
      valueFormatter: (v: unknown) => (typeof v === 'number' ? clock(v) : '—'),
    }
    const s = q.data?.summary
    const summary = t('sleep.schedule.summary', {
      bed: s?.bedtime_avg_min != null ? clock(s.bedtime_avg_min) : '—',
      wake: s?.wake_avg_min != null ? clock(360 + s.wake_avg_min) : '—',
      bedSd: fmtNumber(s?.bedtime_sd_min ?? null, 0),
      wakeSd: fmtNumber(s?.wake_sd_min ?? null, 0),
    })
    return {
      option,
      summary,
      nights,
      table: {
        caption: t('sleep.schedule.caption'),
        columns: [t('chart.col.when'), t('sleep.bedtime'), t('sleep.wake')],
        rows: nights.map((n, i) => [fmtDay(n.date), clock(bed[i] ?? 0), clock(wake[i] ?? 0)]),
      },
      csv: {
        filename: csvName('sonno-orari', range.from, range.to),
        columns: [t('chart.col.date'), t('sleep.bedtime'), t('sleep.wake'), 'durata_a_letto_s'],
        rows: nights.map((n, i) => [n.date, clock(bed[i] ?? 0), clock(wake[i] ?? 0), n.in_bed_s !== null ? Math.round(n.in_bed_s) : null]),
      },
      readout: (i: number) => `${fmtDay(nights[i]?.date)} · ${t('sleep.bedtime')} ${clock(bed[i] ?? 0)} · ${t('sleep.wake')} ${clock(wake[i] ?? 0)}`,
    }
  }, [q.data, range.from, range.to, reduced])

  return (
    <Panel title={t('sleep.schedule.title')} icon={Clock} accent="sleep" testId="chart-sleep-schedule">
      <Async query={q} skeleton={skeleton} isEmpty={() => !built} emptyTitle={t('sleep.schedule.empty')} emptyHint={t('chart.empty.hint')}>
        {() =>
          built && (
            <ChartFrame
              summary={built.summary}
              option={built.option}
              table={built.table}
              csv={built.csv}
              cursor={{ count: built.nights.length, index: cursor, onChange: setCursor, readout: cursor === null ? '' : built.readout(cursor) }}
            />
          )
        }
      </Async>
    </Panel>
  )
}

export type { SleepNight }

// --------------------------------------------------------------------------- workouts

const ACTIVITY_LABELS: Record<string, MessageKey> = {
  WALKING: 'activity.WALKING',
  RUNNING: 'activity.RUNNING',
  BIKING: 'activity.BIKING',
  HIKING: 'activity.HIKING',
  SWIMMING: 'activity.SWIMMING',
}
export function activityLabel(type: string): string {
  const key = ACTIVITY_LABELS[type]
  return key ? t(key) : type.charAt(0) + type.slice(1).toLowerCase().replaceAll('_', ' ')
}

export function WeeklyVolumeChart({ data }: { data: ExerciseResponse }) {
  const reduced = useReducedMotion() ?? false
  const [cursor, setCursor] = useState<number | null>(null)
  const built = useMemo(() => {
    const weeks = data.weekly
    if (!weeks.length || data.summary.count === 0) return null
    const p = palette()
    const hours = weeks.map((w) => Math.round((w.duration_s / 3600) * 100) / 100)
    const option = baseOption(
      weeks.map((w) => fmtDayShort(w.week_start)),
      [{ name: t('workouts.weeklyHours'), color: p.glow, kind: 'bar', data: hours }],
      { unit: 'h', reducedMotion: reduced },
    )
    const total = weeks.reduce((s, w) => s + w.duration_s, 0)
    const summary = t('workouts.weekly.summary', {
      count: data.summary.count,
      total: fmtDuration(total),
      avg: fmtDuration(total / weeks.length),
    })
    return {
      option,
      summary,
      table: {
        caption: t('workouts.weekly.caption'),
        columns: [t('workouts.weekOf'), t('workouts.col.count'), t('workouts.col.duration'), t('workouts.col.kcal')],
        rows: weeks.map((w) => [fmtDay(w.week_start), w.count, fmtDuration(w.duration_s), Math.round(w.kcal)]),
      },
      csv: {
        filename: csvName('allenamenti-settimanali', data.from, data.to),
        columns: ['settimana_dal', 'allenamenti', 'durata_s', 'kcal_attive'],
        rows: weeks.map((w) => [w.week_start, w.count, Math.round(w.duration_s), Math.round(w.kcal)]),
      },
      readout: (i: number) => {
        const w = weeks[i]
        return w ? `${t('workouts.weekOf')} ${fmtDay(w.week_start)} · ${w.count} · ${fmtDuration(w.duration_s)}` : ''
      },
    }
  }, [data, reduced])
  if (!built) return <EmptyState title={t('workouts.none')} hint={t('workouts.noneHint')} />
  return (
    <ChartFrame
      summary={built.summary}
      option={built.option}
      table={built.table}
      csv={built.csv}
      cursor={{ count: data.weekly.length, index: cursor, onChange: setCursor, readout: cursor === null ? '' : built.readout(cursor) }}
    />
  )
}

export function WorkoutsTable({ sessions, from, to }: { sessions: ExerciseRow[]; from: string; to: string }) {
  if (sessions.length === 0) return <EmptyState title={t('workouts.none')} hint={t('workouts.noneHint')} />
  const csv = () =>
    downloadCsv(
      csvName('allenamenti', from, to),
      toCsv(
        ['inizio', 'tipo', 'titolo', 'durata_s', 'kcal_attive', 'fc_media_bpm', 'sorgente'],
        sessions.map((s) => [s.start, s.type, s.title, Math.round(s.duration_s), s.kcal === null ? null : Math.round(s.kcal), s.avg_hr === null ? null : Math.round(s.avg_hr), s.source_package]),
      ),
    )
  return (
    <div className="flex flex-col gap-2">
      <div className="max-h-96 overflow-auto border border-border" tabIndex={0} role="region" aria-label={t('workouts.list')}>
        <table className="w-full border-collapse text-sm" data-testid="workouts-table">
          <caption className="sr-only">{t('workouts.list')}</caption>
          <thead className="sticky top-0 bg-surface-muted">
            <tr>
              {(['workouts.col.type', 'workouts.col.date', 'workouts.col.duration', 'workouts.col.kcal', 'workouts.col.hr'] as const).map((k) => (
                <th key={k} scope="col" className="whitespace-nowrap px-2 py-1.5 text-left font-normal text-fg-muted">
                  {t(k)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id} className="border-t border-border" data-testid="workout-row">
                <th scope="row" className="whitespace-nowrap px-2 py-1.5 text-left font-normal">
                  {s.title || activityLabel(s.type)}
                  <span className="block text-xs text-fg-muted">{activityLabel(s.type)}</span>
                </th>
                <td className="whitespace-nowrap px-2 py-1.5">{fmtDateTime(s.start)}</td>
                <td className="whitespace-nowrap px-2 py-1.5">{fmtDuration(s.duration_s)}</td>
                <td className="whitespace-nowrap px-2 py-1.5">{s.kcal === null ? '—' : `${fmtNumber(s.kcal)} kcal`}</td>
                <td className="whitespace-nowrap px-2 py-1.5">{s.avg_hr === null ? '—' : `${fmtNumber(s.avg_hr)} bpm`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="no-print">
        <button type="button" className="btn min-h-11 text-xs" onClick={csv}>
          <DownloadSimple size={16} aria-hidden />
          {t('chart.exportCsv')}
        </button>
      </div>
    </div>
  )
}

export function WorkoutsSection({ range }: { range: ResolvedRange }) {
  const q = useQuery(exerciseQuery({ from: range.from, to: range.to }))
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <Panel title={t('workouts.weekly.title')} icon={PersonSimpleRun} accent="activity" testId="chart-workouts-weekly">
        <Async query={q} skeleton={skeleton}>
          {(d) => <WeeklyVolumeChart data={d} />}
        </Async>
      </Panel>
      <Panel title={t('workouts.list')} icon={PersonSimpleRun} accent="activity" testId="panel-workouts">
        <Async query={q} skeleton={skeleton}>
          {(d) => <WorkoutsTable sessions={d.sessions} from={d.from} to={d.to} />}
        </Async>
      </Panel>
    </div>
  )
}
