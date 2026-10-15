import { Barbell, Drop, Flame, Footprints, Heartbeat, Moon, Pulse, Ruler, Scales, Waveform } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { exerciseQuery, reportQuery, sleepNightsQuery } from '../api/queries'
import { type KpiSpec, KpiGrid, KpiSection, KpiSkeleton } from '../components/Kpi'
import { SleepScheduleChart, SleepStagesChart, WorkoutsSection } from '../components/DomainCharts'
import { PageTitle } from '../components/hud'
import { TrendChart } from '../components/TrendChart'
import { t } from '../i18n'
import { describeDelta, describeMinutes } from '../lib/delta'
import { fmtDuration, fmtNumber } from '../lib/format'
import { METRICS } from '../lib/metrics'
import { useRange } from '../lib/useRange'
import { clock } from '../components/DomainCharts'
import { ErrorState } from '../components/states'

const GRID = 'grid gap-3 xl:grid-cols-2'

// --------------------------------------------------------------------------- Cuore

export function HeartPage() {
  const [range] = useRange()
  const report = useQuery(reportQuery({ from: range.from, to: range.to }))
  const M = METRICS
  return (
    <div>
      <PageTitle sub={t('heart.page.sub')}>{t('nav.heart')}</PageTitle>
      <KpiSection report={report} defs={[M.heartRate, M.restingHr, M.hrv, M.spo2]} />
      <div className={GRID}>
        <div className="xl:col-span-2">
          <TrendChart def={M.heartRate} range={range} icon={Heartbeat} accent="heart" index={0} />
        </div>
        <TrendChart def={M.restingHr} range={range} icon={Pulse} accent="heart" index={1} />
        <TrendChart def={M.hrv} range={range} icon={Waveform} accent="vitals" index={2} />
        <div className="xl:col-span-2">
          <TrendChart def={M.spo2} range={range} icon={Drop} accent="vitals" index={3} />
        </div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- Sonno

export function SleepPage() {
  const [range] = useRange()
  const nights = useQuery(sleepNightsQuery({ from: range.from, to: range.to }))
  const M = METRICS
  let kpis: React.ReactNode
  if (nights.isPending) kpis = <KpiSkeleton />
  else if (nights.isError) {
    kpis = (
      <div className="hud-panel mb-3">
        <ErrorState error={nights.error} onRetry={() => void nights.refetch()} />
      </div>
    )
  } else {
    const s = nights.data.summary
    const p = nights.data.previous
    const none = s.nights === 0
    const items: KpiSpec[] = [
      {
        id: 'sleep-duration',
        label: `${t('m.sleep')} · ${t('kpi.avgNight')}`,
        value: none ? '—' : fmtDuration(s.avg_asleep_s),
        delta: none ? undefined : describeDelta(s.avg_asleep_s, p.avg_asleep_s),
        stats: none ? undefined : [{ label: t('sleep.inBed'), value: fmtDuration(s.avg_in_bed_s) }],
        hint: none ? t('kpi.noData') : t('sleep.nights', { n: s.nights }),
      },
      {
        id: 'sleep-bedtime',
        label: t('sleep.bedtime.avg'),
        value: s.bedtime_avg_min === null ? '—' : clock(s.bedtime_avg_min),
        delta: s.bedtime_avg_min === null ? undefined : describeMinutes(s.bedtime_avg_min, p.bedtime_avg_min),
        hint: s.bedtime_avg_min === null ? t('kpi.noData') : t('sleep.regularity', { min: fmtNumber(s.bedtime_sd_min, 0) }),
      },
      {
        id: 'sleep-wake',
        label: t('sleep.wake.avg'),
        value: s.wake_avg_min === null ? '—' : clock(360 + s.wake_avg_min),
        delta: s.wake_avg_min === null ? undefined : describeMinutes(s.wake_avg_min, p.wake_avg_min),
        hint: s.wake_avg_min === null ? t('kpi.noData') : t('sleep.regularity', { min: fmtNumber(s.wake_sd_min, 0) }),
      },
      {
        id: 'sleep-regularity',
        label: t('sleep.regularity.title'),
        value: s.bedtime_sd_min === null ? '—' : `±${fmtNumber(s.bedtime_sd_min, 0)}`,
        unit: 'min',
        hint: t('sleep.regularity.hint'),
      },
    ]
    kpis = <KpiGrid items={items} />
  }
  return (
    <div>
      <PageTitle sub={t('sleep.page.sub')}>{t('nav.sleep')}</PageTitle>
      {kpis}
      <div className={GRID}>
        <div className="xl:col-span-2">
          <TrendChart def={M.sleep} range={range} icon={Moon} accent="sleep" index={0} />
        </div>
        <SleepStagesChart range={range} />
        <SleepScheduleChart range={range} />
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- Attività

export function ActivityPage() {
  const [range] = useRange()
  const report = useQuery(reportQuery({ from: range.from, to: range.to }))
  const workouts = useQuery(exerciseQuery({ from: range.from, to: range.to }))
  const M = METRICS
  const w = workouts.data
  const extra: KpiSpec[] = [
    {
      id: 'workouts',
      label: `${t('workouts.title')} · ${t('kpi.total')}`,
      value: w ? fmtNumber(w.summary.count) : '…',
      delta: w ? describeDelta(w.summary.duration_s, w.previous.duration_s) : undefined,
      stats: w
        ? [
            { label: t('workouts.col.duration'), value: fmtDuration(w.summary.duration_s) },
            { label: t('workouts.avgDuration'), value: fmtDuration(w.summary.avg_duration_s) },
          ]
        : undefined,
      hint: w && w.summary.count === 0 ? t('kpi.noData') : undefined,
    },
  ]
  return (
    <div>
      <PageTitle sub={t('activity.page.sub')}>{t('nav.activity')}</PageTitle>
      <KpiSection report={report} defs={[M.steps, M.distance, M.activeKcal, M.totalKcal]} extra={extra} />
      <div className={GRID}>
        <TrendChart def={M.steps} range={range} icon={Footprints} accent="activity" index={0} />
        <TrendChart def={M.distance} range={range} icon={Ruler} accent="activity" index={1} />
        <TrendChart def={M.activeKcal} range={range} icon={Flame} accent="energy" index={2} />
        <TrendChart def={M.totalKcal} range={range} icon={Flame} accent="energy" index={3} />
      </div>
      <h2 className="hud-label mb-2 mt-5 flex items-center gap-2">
        <Barbell size={18} aria-hidden /> {t('workouts.title')}
      </h2>
      <WorkoutsSection range={range} />
    </div>
  )
}

// --------------------------------------------------------------------------- Corpo

export function BodyPage() {
  const [range] = useRange()
  const report = useQuery(reportQuery({ from: range.from, to: range.to }))
  const M = METRICS
  const refs = [
    { from: 90, to: 120, label: t('bp.ref.sys'), series: 0 as const },
    { from: 60, to: 80, label: t('bp.ref.dia'), series: 1 as const },
  ]
  return (
    <div>
      <PageTitle sub={t('body.page.sub')}>{t('nav.body')}</PageTitle>
      <KpiSection report={report} defs={[M.weight, M.systolic, M.diastolic]} />
      <div className={GRID}>
        <TrendChart def={M.weight} range={range} icon={Scales} accent="glow" index={0} />
        <TrendChart
          def={M.systolic}
          pair={M.diastolic}
          range={range}
          icon={Heartbeat}
          accent="heart"
          index={1}
          reference={refs}
          referenceNote={t('bp.ref.note')}
          emptyTitle={t('bp.empty.title')}
          emptyHint={t('bp.empty.hint')}
        />
      </div>
    </div>
  )
}
