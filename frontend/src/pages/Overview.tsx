import {
  Drop,
  Fire,
  Footprints,
  Heartbeat,
  Moon,
  PersonSimpleRun,
  Pulse,
  TrendUp,
} from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { seriesQuery, summaryQuery } from '../api/queries'
import type { MetricValue, SleepSummary, TodaySummary } from '../api/types'
import { SeriesChartCard } from '../components/ChartCard'
import { Ring } from '../components/gauges'
import { HeartPointsWeekPanel } from '../components/HeartPoints'
import { Panel, PageTitle, Stat } from '../components/hud'
import { Async, EmptyState, SkeletonLines } from '../components/states'
import { t } from '../i18n'
import { type MessageKey } from '../i18n'
import {
  fmtDateTime,
  fmtDay,
  fmtDayLong,
  fmtDistance,
  fmtDuration,
  fmtNumber,
  fmtTime,
  timeAgo,
} from '../lib/format'
import { STEP_GOAL } from '../lib/goals'
import { useRange } from '../lib/useRange'

const panelSkeleton = <div className="min-h-32"><SkeletonLines lines={3} height="h-8" /></div>

/** True when official and computed disagree by more than rounding (worth a visible note). */
function disagrees(m: MetricValue): boolean {
  if (m.official === null || m.computed === null) return false
  return Math.abs(m.official - m.computed) > Math.max(1, Math.abs(m.official) * 0.02)
}

function SourceNote({ m, digits = 0 }: { m: MetricValue; digits?: number }) {
  if (m.value === null) return null
  if (m.source === 'computed') return <span>{t('metric.onlyComputed')}</span>
  if (!disagrees(m)) return <span>{t('metric.official')}</span>
  return (
    <span>
      {t('metric.officialVsComputed', {
        official: fmtNumber(m.official, digits),
        computed: fmtNumber(m.computed, digits),
      })}
    </span>
  )
}

function StepsPanel({ s }: { s: TodaySummary }) {
  const steps = s.steps.value
  const fraction = steps === null ? 0 : steps / STEP_GOAL
  return (
    <div className="flex flex-wrap items-center gap-4">
      <Ring
        fraction={fraction}
        label={t('steps.ringLabel', { value: fmtNumber(steps), goal: fmtNumber(STEP_GOAL) })}
      >
        <span className="hud-number text-3xl" data-testid="steps-value">
          {fmtNumber(steps)}
        </span>
        <span className="hud-label">{t('steps.unit')}</span>
      </Ring>
      <div className="flex min-w-0 flex-col gap-2 text-sm">
        <div>
          <span className="text-fg-muted">{t('steps.goal')} </span>
          {fmtNumber(STEP_GOAL)}
        </div>
        <div>
          <span className="text-fg-muted">{t('steps.distance')} </span>
          {fmtDistance(s.distance_m.value)}
        </div>
        <div className="text-xs text-fg-muted">
          <SourceNote m={s.steps} />
        </div>
      </div>
    </div>
  )
}

function HeartPanel({ s }: { s: TodaySummary }) {
  const h = s.heart
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <Stat
          label={t('heart.current')}
          value={fmtNumber(h.current?.value ?? null)}
          unit="bpm"
          hint={h.current ? t('heart.sampleAt', { when: timeAgo(h.current.time) }) : t('heart.noSample')}
        />
        <Stat
          label={t('heart.resting')}
          value={fmtNumber(h.resting.value, 0)}
          unit="bpm"
          size="md"
          hint={h.resting.date ? fmtDay(h.resting.date) : undefined}
        />
      </div>
      <p className="text-sm text-fg-muted">
        {h.samples > 0
          ? t('heart.today', {
              min: fmtNumber(h.min),
              avg: fmtNumber(h.avg),
              max: fmtNumber(h.max),
              count: fmtNumber(h.samples),
            })
          : t('heart.noToday')}
      </p>
    </div>
  )
}

const STAGE_ORDER = ['deep', 'rem', 'light', 'sleeping', 'awake', 'awake_in_bed', 'out_of_bed', 'unknown'] as const
const STAGE_OPACITY: Record<string, number> = { deep: 1, rem: 0.78, light: 0.5, sleeping: 0.6 }

function SleepPanel({ sleep }: { sleep: SleepSummary | null }) {
  if (!sleep) return <EmptyState title={t('sleep.none')} hint={t('sleep.noneHint')} />
  const stages = STAGE_ORDER.filter((k) => (sleep.stages_s[k] ?? 0) > 0)
  const total = stages.reduce((a, k) => a + (sleep.stages_s[k] ?? 0), 0)
  return (
    <div className="flex flex-col gap-3">
      <Stat
        value={fmtDuration(sleep.asleep_s)}
        size="md"
        hint={
          <>
            {t('sleep.night', { date: fmtDayLong(sleep.date) })}
            {sleep.start && sleep.end && ` · ${fmtTime(sleep.start)}–${fmtTime(sleep.end)}`}
          </>
        }
      />
      {total > 0 && (
        <>
          {/* Segment widths and opacities carry the data visually; the legend carries it in words. */}
          <div className="flex h-3 w-full overflow-hidden border border-border-control" aria-hidden>
            {stages.map((k) => (
              <span
                key={k}
                style={{
                  width: `${((sleep.stages_s[k] ?? 0) / total) * 100}%`,
                  background: 'var(--color-m-sleep)',
                  opacity: STAGE_OPACITY[k] ?? 0.25,
                  borderRight: '1px solid var(--color-bg)',
                }}
              />
            ))}
          </div>
          <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-fg-muted" data-testid="sleep-stages">
            {stages.map((k) => (
              <li key={k} className="flex justify-between gap-2">
                <span>{t(`stage.${k}` as MessageKey)}</span>
                <span className="text-fg">{fmtDuration(sleep.stages_s[k])}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

function EnergyPanel({ s }: { s: TodaySummary }) {
  return (
    <div className="flex flex-col gap-3">
      <Stat
        label={t('energy.active')}
        value={fmtNumber(s.active_kcal.value)}
        unit="kcal"
        hint={<SourceNote m={s.active_kcal} />}
      />
      <div className="text-sm text-fg-muted">
        {t('energy.total')} <span className="text-fg">{fmtNumber(s.total_kcal.value)} kcal</span>
      </div>
    </div>
  )
}

function VitalsPanel({ s }: { s: TodaySummary }) {
  return (
    <div className="flex flex-wrap gap-x-8 gap-y-4">
      <Stat
        label={t('vitals.spo2')}
        value={fmtNumber(s.spo2.value, 1)}
        unit="%"
        size="md"
        hint={s.spo2.date ? fmtDay(s.spo2.date) : t('vitals.none')}
      />
      <Stat
        label={t('vitals.hrv')}
        value={fmtNumber(s.hrv.value, 0)}
        unit="ms"
        size="md"
        hint={s.hrv.date ? fmtDay(s.hrv.date) : t('vitals.none')}
      />
    </div>
  )
}

function ActivitiesPanel({ s }: { s: TodaySummary }) {
  if (s.activities.length === 0) return <EmptyState title={t('activities.none')} />
  return (
    <ul className="flex flex-col divide-y divide-border" data-testid="activities">
      {s.activities.map((a) => (
        <li key={a.id} className="flex items-baseline justify-between gap-3 py-2">
          <span className="min-w-0">
            <span className="block truncate">{a.title || activityLabel(a.type)}</span>
            <span className="block text-xs text-fg-muted">{fmtDateTime(a.start)}</span>
          </span>
          <span className="shrink-0 text-sm">{fmtDuration(a.duration_s)}</span>
        </li>
      ))}
    </ul>
  )
}

const ACTIVITY_LABELS: Record<string, MessageKey> = {
  WALKING: 'activity.WALKING',
  RUNNING: 'activity.RUNNING',
  BIKING: 'activity.BIKING',
  HIKING: 'activity.HIKING',
  SWIMMING: 'activity.SWIMMING',
}

function activityLabel(type: string): string {
  const key = ACTIVITY_LABELS[type]
  return key ? t(key) : type.charAt(0) + type.slice(1).toLowerCase().replaceAll('_', ' ')
}

export function OverviewPage() {
  const summary = useQuery(summaryQuery())
  const [range] = useRange()
  const bucket = range.days <= 1 ? 'hour' : range.days <= 120 ? 'day' : 'auto'
  const stepsSeries = useQuery(seriesQuery({ type: 'Steps', from: range.from, to: range.to, bucket }))
  const restingSeries = useQuery(
    seriesQuery({
      type: 'RestingHeartRate',
      from: range.from,
      to: range.to,
      bucket: range.days <= 1 ? 'day' : bucket,
      agg: 'avg',
    }),
  )

  return (
    <div>
      <PageTitle sub={summary.data ? t('overview.sub', { date: fmtDayLong(summary.data.date) }) : undefined}>
        {t('overview.title')}
      </PageTitle>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-12">
        <Panel title={t('steps.title')} icon={Footprints} accent="activity" className="xl:col-span-4" index={0} testId="panel-steps">
          <Async query={summary} skeleton={panelSkeleton}>
            {(s) => <StepsPanel s={s} />}
          </Async>
        </Panel>

        <Panel title={t('heart.title')} icon={Heartbeat} accent="heart" className="xl:col-span-4" index={1} testId="panel-heart">
          <Async query={summary} skeleton={panelSkeleton}>
            {(s) => <HeartPanel s={s} />}
          </Async>
        </Panel>

        <Panel title={t('sleep.title')} icon={Moon} accent="sleep" className="xl:col-span-4" index={2} testId="panel-sleep">
          <Async query={summary} skeleton={panelSkeleton}>
            {(s) => <SleepPanel sleep={s.sleep} />}
          </Async>
        </Panel>

        <div className="flex flex-col gap-3 xl:col-span-4">
          <Panel title={t('energy.title')} icon={Fire} accent="energy" className="flex-1" index={3} testId="panel-energy">
            <Async query={summary} skeleton={panelSkeleton}>
              {(s) => <EnergyPanel s={s} />}
            </Async>
          </Panel>
          <Panel title={t('vitals.title')} icon={Drop} accent="vitals" className="flex-1" index={4} testId="panel-vitals">
            <Async query={summary} skeleton={panelSkeleton}>
              {(s) => <VitalsPanel s={s} />}
            </Async>
          </Panel>
          {/* always the week that contains the END of the selected window (today unless moved back) */}
          <HeartPointsWeekPanel day={range.to} index={5} />
        </div>

        <Panel title={t('activities.title')} icon={PersonSimpleRun} accent="activity" className="md:col-span-2 xl:col-span-8" index={5} testId="panel-activities">
          <Async query={summary} skeleton={panelSkeleton}>
            {(s) => <ActivitiesPanel s={s} />}
          </Async>
        </Panel>

        <SeriesChartCard
          title={t('trend.steps')}
          icon={TrendUp}
          accent="activity"
          query={stepsSeries}
          kind="bar"
          label={t('steps.title')}
          color="glow"
          className="md:col-span-2 xl:col-span-7"
          index={6}
          testId="chart-steps"
        />
        <SeriesChartCard
          title={t('trend.resting')}
          icon={Pulse}
          accent="heart"
          query={restingSeries}
          kind="line"
          label={t('heart.resting')}
          color="heart"
          className="md:col-span-2 xl:col-span-5"
          index={7}
          testId="chart-resting"
        />
      </div>
    </div>
  )
}
