import {
  ArrowsClockwise,
  CheckCircle,
  Database,
  Scales,
  Warning,
  XCircle,
  MinusCircle,
  CopySimple,
} from '@phosphor-icons/react'
import * as Tabs from '@radix-ui/react-tabs'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useReducedMotion } from 'motion/react'
import { useMemo, useState } from 'react'
import { inventoryQuery, reconciliationQuery, syncStatusQuery } from '../api/queries'
import type { AlarmInfo, ReconStatus, ReconciliationRow, SyncRunRow } from '../api/types'
import { ChartFrame, type TableSpec } from '../components/ChartCard'
import { Badge, PageTitle, Panel } from '../components/hud'
import { StorageTab } from '../components/StoragePanel'
import { Async, SkeletonLines } from '../components/states'
import { t } from '../i18n'
import { baseOption, palette } from '../lib/charts'
import {
  addDays,
  daysBetween,
  fmtDateTime,
  fmtDay,
  fmtDuration,
  fmtNumber,
  fmtPercent,
  timeAgo,
} from '../lib/format'
import { useRange } from '../lib/useRange'

const TABS = ['sync', 'inventory', 'recon', 'storage'] as const
type TabId = (typeof TABS)[number]

const RECON_TYPES = ['Steps', 'Distance', 'ActiveCaloriesBurned', 'TotalCaloriesBurned', 'SleepSession']
const RECON_MAX_DAYS = 120

function fmtValue(v: number | null, unit: string | null): string {
  if (v === null) return '—'
  if (unit === 's') return fmtDuration(v)
  const suffix = unit && unit !== 'count' ? ` ${unit}` : ''
  return `${fmtNumber(v, unit === 'm' || unit === 'kcal' || unit === 'count' ? 0 : 1)}${suffix}`
}

const tableWrap = 'overflow-x-auto border border-border'
const th = 'whitespace-nowrap px-2 py-1.5 text-left font-normal text-fg-muted'
const td = 'whitespace-nowrap px-2 py-1.5'

// --------------------------------------------------------------------------- Sync tab

function runTone(s: SyncRunRow['status']) {
  return s === 'completed' ? 'ok' : s === 'running' ? 'muted' : s === 'partial' ? 'warn' : 'danger'
}
const RUN_ICON = { completed: CheckCircle, running: ArrowsClockwise, partial: Warning, failed: XCircle } as const

function RunItem({ run }: { run: SyncRunRow }) {
  const Icon = RUN_ICON[run.status]
  const hasProblems = run.rejected > 0 || run.errors.length > 0
  return (
    <details className="border-b border-border last:border-b-0" data-testid="sync-run" open={hasProblems && run.status !== 'completed'}>
      <summary className="flex min-h-11 flex-wrap items-center gap-x-4 gap-y-1 py-2">
        <Badge tone={runTone(run.status)} icon={Icon}>
          {t(`run.status.${run.status}` as const)}
        </Badge>
        <span>{fmtDateTime(run.started_at)}</span>
        <span className="text-fg-muted">{run.device_name ?? run.device_id.slice(0, 8)}</span>
        <span className="text-fg-muted">{run.mode ? t(`run.mode.${run.mode}` as never) : '—'}</span>
        <span className="text-fg-muted">{fmtDuration(run.duration_s)}</span>
        <span className="ml-auto flex gap-3 text-sm">
          <span>
            {t('run.received')} <b className="font-normal">{fmtNumber(run.received)}</b>
          </span>
          {run.rejected > 0 && (
            <span className="text-danger-text">
              {t('run.rejected')} <b className="font-normal">{fmtNumber(run.rejected)}</b>
            </span>
          )}
        </span>
      </summary>
      <div className="grid gap-4 pb-4 pl-2 text-sm md:grid-cols-2">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
          {(
            [
              ['run.inserted', run.inserted],
              ['run.updated', run.updated],
              ['run.unchanged', run.unchanged],
              ['run.rejected', run.rejected],
              ['run.deletions', run.deletions],
              ['run.aggregates', run.aggregates],
            ] as const
          ).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-fg-muted">{t(k)}</dt>
              <dd>{fmtNumber(v)}</dd>
            </div>
          ))}
        </dl>
        <div className="flex flex-col gap-3">
          {run.rejections.length > 0 && (
            <div>
              <h4 className="hud-label mb-1">{t('run.rejections')}</h4>
              <ul className="flex flex-col gap-1">
                {run.rejections.map((r) => (
                  <li key={`${r.type}|${r.reason}`}>
                    <b className="font-normal text-danger-text">{fmtNumber(r.count)}×</b> {r.type} · {r.reason}
                    {r.detail && <span className="block text-xs text-fg-muted">{r.detail}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {run.errors.length > 0 && (
            <div>
              <h4 className="hud-label mb-1">{t('run.errors')}</h4>
              <ul className="flex flex-col gap-1">
                {run.errors.map((e, i) => (
                  <li key={i}>
                    <b className="font-normal text-danger-text">{e.code}</b>
                    {e.type && ` · ${e.type}`}
                    {e.count !== undefined && ` ×${e.count}`}
                    {e.message && <span className="block text-xs text-fg-muted">{e.message}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {run.reported_counts && (
            <div>
              <h4 className="hud-label mb-1">{t('run.reported')}</h4>
              <p className="text-xs text-fg-muted">
                {Object.entries(run.reported_counts)
                  .map(([k, v]) => `${k}: ${fmtNumber(v)}`)
                  .join(' · ')}
              </p>
            </div>
          )}
          {!hasProblems && <p className="text-fg-muted">{t('run.clean')}</p>}
        </div>
      </div>
    </details>
  )
}

function AlarmLine({ alarm }: { alarm: AlarmInfo }) {
  const threshold = fmtNumber(alarm.threshold_hours, alarm.threshold_hours % 1 === 0 ? 0 : 1)
  const hours = alarm.hours_since_sync === null ? '—' : fmtNumber(alarm.hours_since_sync, 1)
  const text =
    alarm.status === 'never'
      ? t('sync.alarm.never', { threshold })
      : alarm.status === 'stale'
        ? t('sync.alarm.stale', { hours, threshold })
        : t('sync.alarm.ok', { hours, threshold })
  const tone = alarm.status === 'ok' ? 'ok' : alarm.status === 'stale' ? 'danger' : 'muted'
  const Icon = alarm.status === 'ok' ? CheckCircle : alarm.status === 'stale' ? Warning : MinusCircle
  return (
    <div data-testid="sync-alarm" data-alarm={alarm.status} role="status">
      <div className="hud-label">{t('sync.alarm')}</div>
      <Badge tone={tone} icon={Icon}>
        {text}
      </Badge>
      <p className="mt-1 text-xs text-fg-muted">{t('sync.alarm.hint')}</p>
    </div>
  )
}

function SyncTab() {
  const q = useQuery(syncStatusQuery())
  return (
    <div className="grid gap-3 xl:grid-cols-12">
      <Panel title={t('sync.status')} icon={ArrowsClockwise} accent="glow" className="xl:col-span-4" testId="panel-sync-status">
        <Async query={q} skeleton={<SkeletonLines />}>
          {(d) => (
            <div className="flex flex-col gap-3 text-sm">
              <div>
                <div className="hud-label">{t('sync.lastSuccess')}</div>
                <div className="text-lg">{d.last_success_at ? timeAgo(d.last_success_at) : t('link.never')}</div>
                <div className="text-fg-muted">{fmtDateTime(d.last_success_at)}</div>
              </div>
              <AlarmLine alarm={d.alarm} />
              <div>
                <div className="hud-label">{t('sync.devices')}</div>
                {d.devices.length === 0 ? (
                  <p className="text-fg-muted">{t('sync.noDevices')}</p>
                ) : (
                  <ul className="flex flex-col gap-1">
                    {d.devices.map((dev) => (
                      <li key={dev.id} data-testid="sync-device">
                        {dev.name ?? dev.model ?? dev.id.slice(0, 8)}
                        {dev.app_version && <span className="text-fg-muted"> · v{dev.app_version}</span>}
                        <span className="block text-xs text-fg-muted">
                          {dev.last_success_at
                            ? t('sync.deviceSuccess', { when: timeAgo(dev.last_success_at) })
                            : t('sync.deviceNoSuccess')}
                          {' · '}
                          {t('sync.seen', { when: timeAgo(dev.last_seen_at) })}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </Async>
      </Panel>

      <Panel title={t('sync.runs')} icon={Database} accent="glow" className="xl:col-span-8" index={1} testId="panel-sync-runs">
        <Async
          query={q}
          skeleton={<SkeletonLines lines={5} height="h-9" />}
          isEmpty={(d) => d.runs.length === 0}
          emptyTitle={t('sync.noRuns')}
          emptyHint={t('sync.noRunsHint')}
        >
          {(d) => (
            <div>
              {d.runs.map((r) => (
                <RunItem key={r.sync_id} run={r} />
              ))}
            </div>
          )}
        </Async>
      </Panel>
    </div>
  )
}

// --------------------------------------------------------------------------- Inventory tab

function InventoryTab() {
  const q = useQuery(inventoryQuery())
  return (
    <div className="flex flex-col gap-3">
      <Panel title={t('inv.sources')} icon={Database} accent="glow" testId="panel-sources">
        <Async
          query={q}
          skeleton={<SkeletonLines lines={3} />}
          isEmpty={(d) => d.records === 0}
          emptyTitle={t('inv.empty')}
          emptyHint={t('inv.emptyHint')}
        >
          {(d) => (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-fg-muted" data-testid="inv-totals">
                {t('inv.totals', {
                  records: fmtNumber(d.records),
                  samples: fmtNumber(d.samples),
                  deleted: fmtNumber(d.deleted),
                })}
              </p>
              <ul className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {d.sources.map((s) => (
                  <li key={s.package} className="border border-border p-3" data-testid="source-card">
                    <div className="break-all text-fg">{s.package}</div>
                    <div className="hud-number mt-1 text-2xl">{fmtNumber(s.records)}</div>
                    <div className="text-xs text-fg-muted">
                      {fmtDateTime(s.first)} → {fmtDateTime(s.last)}
                    </div>
                    <div className="mt-2 text-xs text-fg-muted">{s.types.join(', ')}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Async>
      </Panel>

      <Panel title={t('inv.types')} icon={Database} accent="glow" index={1} testId="panel-types">
        <Async query={q} skeleton={<SkeletonLines lines={6} height="h-8" />} isEmpty={(d) => d.types.length === 0}>
          {(d) => (
            <div className={tableWrap} tabIndex={0} role="region" aria-label={t('inv.types')}>
              <table className="w-full border-collapse text-sm">
                <thead className="bg-surface-muted">
                  <tr>
                    {(
                      [
                        'inv.col.type',
                        'inv.col.records',
                        'inv.col.deleted',
                        'inv.col.samples',
                        'inv.col.first',
                        'inv.col.last',
                        'inv.col.sources',
                        'inv.col.days',
                      ] as const
                    ).map((k) => (
                      <th key={k} scope="col" className={th}>
                        {t(k)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.types.map((ty) => (
                    <tr key={ty.type} className="border-t border-border align-top" data-testid="type-row">
                      <th scope="row" className={`${td} text-left font-normal`}>
                        {ty.type}
                        <span className="block text-xs text-fg-muted">{ty.unit ?? ''}</span>
                      </th>
                      <td className={td}>{fmtNumber(ty.records)}</td>
                      <td className={td}>{fmtNumber(ty.deleted)}</td>
                      <td className={td}>{ty.samples ? fmtNumber(ty.samples) : '—'}</td>
                      <td className={td}>{fmtDateTime(ty.first)}</td>
                      <td className={td}>{fmtDateTime(ty.last)}</td>
                      <td className="px-2 py-1.5">
                        <ul className="flex flex-col gap-0.5 text-xs">
                          {ty.sources.map((s) => (
                            <li key={s.package} className="whitespace-nowrap">
                              {s.package} <span className="text-fg-muted">· {fmtNumber(s.records)}</span>
                            </li>
                          ))}
                        </ul>
                      </td>
                      <td className={td}>
                        {fmtNumber(ty.official_days)} / {fmtNumber(ty.computed_days)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Async>
      </Panel>
    </div>
  )
}

// --------------------------------------------------------------------------- Reconciliation tab

const STATUS_VIEW: Record<ReconStatus, { tone: 'ok' | 'warn' | 'muted' | 'danger'; icon: typeof CheckCircle }> = {
  match: { tone: 'ok', icon: CheckCircle },
  diff: { tone: 'warn', icon: Warning },
  no_official: { tone: 'muted', icon: MinusCircle },
  no_computed: { tone: 'muted', icon: MinusCircle },
  no_data: { tone: 'muted', icon: MinusCircle },
}

function ReconRowItem({ row }: { row: ReconciliationRow }) {
  const view = STATUS_VIEW[row.status]
  return (
    <tr className="border-t border-border align-top" data-testid="recon-row" data-status={row.status}>
      <th scope="row" className={`${td} text-left font-normal`}>
        {fmtDay(row.date)}
        <span className="block text-xs text-fg-muted">{row.type}</span>
      </th>
      <td className={td}>{fmtValue(row.official, row.unit)}</td>
      <td className={td}>{fmtValue(row.computed, row.unit)}</td>
      <td className={td}>
        {fmtValue(row.naive, row.unit)}
        {row.naive_exceeds_official && (
          <span className="mt-1 block">
            <Badge tone="warn" icon={CopySimple}>
              {t('recon.overlap')}
            </Badge>
          </span>
        )}
      </td>
      <td className={td}>{row.diff_pct === null ? '—' : fmtPercent(row.diff_pct)}</td>
      <td className={td}>
        <Badge tone={view.tone} icon={view.icon}>
          {t(`recon.status.${row.status}` as const)}
        </Badge>
      </td>
      <td className="px-2 py-1.5">
        <ul className="flex flex-col gap-0.5 text-xs">
          {row.sources.map((s) => (
            <li key={s.package} className="whitespace-nowrap">
              {s.package}{' '}
              <span className="text-fg-muted">
                · {fmtValue(s.raw, row.unit)}
                {s.counted !== null && ` → ${fmtValue(s.counted, row.unit)}`}
              </span>
            </li>
          ))}
        </ul>
      </td>
    </tr>
  )
}

function ReconTab() {
  const [range] = useRange()
  const [type, setType] = useState<string>('Steps')
  const reduced = useReducedMotion() ?? false

  // The API caps the window at 120 days: clamp from the end and say so.
  const clamped = range.days > RECON_MAX_DAYS
  const from = clamped ? addDays(range.to, -(RECON_MAX_DAYS - 1)) : range.from
  const q = useQuery(reconciliationQuery({ from, to: range.to, types: type }))

  const built = useMemo(() => {
    const d = q.data
    if (!d || d.rows.length === 0) return null
    const rows = [...d.rows].sort((a, b) => a.date.localeCompare(b.date))
    const unit = rows[0]?.unit ?? null
    const scale = unit === 's' ? 3600 : 1
    const u = unit === 's' ? 'h' : (unit ?? '')
    const pick = (f: (r: ReconciliationRow) => number | null) =>
      rows.map((r) => {
        const v = f(r)
        return v === null ? null : Math.round((v / scale) * 10) / 10
      })
    const p = palette()
    const option = baseOption(
      rows.map((r) => fmtDay(r.date)),
      [
        { name: t('recon.col.official'), color: p.glow, kind: 'bar', data: pick((r) => r.official) },
        { name: t('recon.col.computed'), color: p.accent, kind: 'bar', data: pick((r) => r.computed) },
        { name: t('recon.col.naive'), color: p.warn, kind: 'line', dashed: true, data: pick((r) => r.naive) },
      ],
      { unit: u, showLegend: true, reducedMotion: reduced },
    )
    const table: TableSpec = {
      caption: t('recon.tableCaption', { type }),
      columns: [
        t('chart.col.when'),
        t('recon.col.official'),
        t('recon.col.computed'),
        t('recon.col.naive'),
        t('recon.col.delta'),
      ],
      rows: rows.map((r) => [
        fmtDay(r.date),
        fmtValue(r.official, r.unit),
        fmtValue(r.computed, r.unit),
        fmtValue(r.naive, r.unit),
        r.diff_pct === null ? '—' : fmtPercent(r.diff_pct),
      ]),
    }
    const s = d.summary
    const summary = t('recon.summary', {
      type,
      days: daysBetween(from, range.to) + 1,
      matches: s.matches,
      diffs: s.diffs,
      noOfficial: s.no_official,
      overlap: s.overlap_rows,
    })
    return { option, table, summary }
  }, [q.data, type, from, range.to, reduced])

  return (
    <div className="flex flex-col gap-3">
      <Panel title={t('recon.title')} icon={Scales} accent="glow" testId="panel-recon">
        <p className="text-sm text-fg-muted">{t('recon.intro')}</p>
        <div className="flex flex-wrap items-center gap-3">
          <label htmlFor="recon-type" className="hud-label">
            {t('recon.type')}
          </label>
          <select id="recon-type" className="input w-auto" value={type} onChange={(e) => setType(e.target.value)}>
            {RECON_TYPES.map((x) => (
              <option key={x} value={x}>
                {x}
              </option>
            ))}
          </select>
          {clamped && <span className="text-sm text-warn">{t('recon.clamped', { days: RECON_MAX_DAYS })}</span>}
        </div>
        <Async
          query={q}
          skeleton={<SkeletonLines lines={4} height="h-9" />}
          isEmpty={(d) => d.rows.length === 0}
          emptyTitle={t('recon.empty')}
          emptyHint={t('recon.emptyHint')}
        >
          {() => built && <ChartFrame summary={built.summary} option={built.option} table={built.table} height={260} />}
        </Async>
      </Panel>

      <Panel title={t('recon.detail')} icon={Scales} accent="glow" index={1} testId="panel-recon-table">
        <Async query={q} skeleton={<SkeletonLines lines={6} height="h-8" />} isEmpty={(d) => d.rows.length === 0}>
          {(d) => (
            <div className={tableWrap} tabIndex={0} role="region" aria-label={t('recon.detail')}>
              <table className="w-full border-collapse text-sm">
                <thead className="bg-surface-muted">
                  <tr>
                    {(
                      [
                        'recon.col.day',
                        'recon.col.official',
                        'recon.col.computed',
                        'recon.col.naive',
                        'recon.col.delta',
                        'recon.col.status',
                        'recon.col.sources',
                      ] as const
                    ).map((k) => (
                      <th key={k} scope="col" className={th}>
                        {t(k)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {d.rows.map((r) => (
                    <ReconRowItem key={`${r.date}|${r.type}`} row={r} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Async>
      </Panel>
    </div>
  )
}

// --------------------------------------------------------------------------- page

export function SyncDataPage() {
  const search = useSearch({ strict: false }) as { tab?: string }
  const navigate = useNavigate()
  const tab: TabId = (TABS as readonly string[]).includes(search.tab ?? '') ? (search.tab as TabId) : 'sync'
  const setTab = (next: string) =>
    void navigate({
      to: '.',
      search: ((prev: Record<string, unknown>) => ({ ...prev, tab: next === 'sync' ? undefined : next })) as never,
    })

  return (
    <div>
      <PageTitle sub={t('sync.sub')}>{t('sync.title')}</PageTitle>
      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List aria-label={t('sync.title')} className="mb-3 flex flex-wrap border border-border-control">
          {TABS.map((id) => (
            <Tabs.Trigger
              key={id}
              value={id}
              className="min-h-11 flex-1 border-r border-border-control px-3 font-display uppercase tracking-wider last:border-r-0 data-[state=active]:bg-accent data-[state=active]:text-black hover:bg-accent-glow/10 data-[state=active]:hover:bg-accent"
            >
              {t(`tab.${id}` as const)}
            </Tabs.Trigger>
          ))}
        </Tabs.List>
        <Tabs.Content value="sync" className="outline-offset-4">
          <SyncTab />
        </Tabs.Content>
        <Tabs.Content value="inventory" className="outline-offset-4">
          <InventoryTab />
        </Tabs.Content>
        <Tabs.Content value="recon" className="outline-offset-4">
          <ReconTab />
        </Tabs.Content>
        <Tabs.Content value="storage" className="outline-offset-4">
          <StorageTab />
        </Tabs.Content>
      </Tabs.Root>
    </div>
  )
}

