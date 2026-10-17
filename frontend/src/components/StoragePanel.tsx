import { ArrowDown, ArrowUp, Database, HardDrives, ListChecks } from '@phosphor-icons/react'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { storageQuery } from '../api/queries'
import type { LimitItem, StorageResponse, TableStorage } from '../api/types'
import { t } from '../i18n'
import { fmtBytes, fmtDateTime, fmtNumber } from '../lib/format'
import { KpiGrid, type KpiSpec } from './Kpi'
import { Panel } from './hud'
import { Async, SkeletonLines } from './states'

/** One sentence per limit/retention item: the wording lives in i18n, the values come from the API. */
export function limitText(item: LimitItem): string {
  const p = item.params as Record<string, number>
  switch (item.id) {
    case 'retention':
      return t('storage.limit.retention')
    case 'soft_delete':
      return t('storage.limit.softDelete')
    case 'session_purge':
      return t('storage.limit.sessionPurge', {
        minute: String(p.minute).padStart(2, '0'),
        days: fmtNumber(Math.round((p.session_ttl_hours ?? 0) / 24)),
      })
    case 'daily_recompute':
      return t('storage.limit.dailyRecompute', {
        time: `${String(p.hour).padStart(2, '0')}:${String(p.minute).padStart(2, '0')}`,
      })
    case 'stale_alarm':
      return t('storage.limit.staleAlarm', { hours: fmtNumber(p.threshold_hours) })
    case 'ingest_batch':
      return t('storage.limit.ingestBatch', { n: fmtNumber(p.max_records) })
    case 'ingest_body':
      return t('storage.limit.ingestBody', { size: fmtBytes(p.max_bytes) })
    case 'route_points':
      return t('storage.limit.routePoints', { n: fmtNumber(p.max_points) })
    case 'query_days':
      return t('storage.limit.queryDays', { n: fmtNumber(p.max_days) })
    case 'intraday':
      return t('storage.limit.intraday', {
        quarter: fmtNumber(p.minutes_15_max_days),
        hour: fmtNumber(p.hour_max_days),
      })
    case 'chart_points':
      return t('storage.limit.chartPoints', { n: fmtNumber(p.max_points) })
  }
}

type SortKey = 'name' | 'total_bytes' | 'data_bytes' | 'index_bytes' | 'rows'
type SortDir = 'ascending' | 'descending'

const COLUMNS: { key: SortKey; label: Parameters<typeof t>[0] }[] = [
  { key: 'name', label: 'storage.col.table' },
  { key: 'total_bytes', label: 'storage.col.total' },
  { key: 'data_bytes', label: 'storage.col.data' },
  { key: 'index_bytes', label: 'storage.col.index' },
  { key: 'rows', label: 'storage.col.rows' },
]

export function sortTables(tables: TableStorage[], key: SortKey, dir: SortDir): TableStorage[] {
  const sign = dir === 'ascending' ? 1 : -1
  return [...tables].sort((a, b) => {
    const diff = key === 'name' ? a.name.localeCompare(b.name) : a[key] - b[key]
    return diff === 0 ? a.name.localeCompare(b.name) : sign * diff
  })
}

function TablesTable({ tables }: { tables: TableStorage[] }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: 'total_bytes', dir: 'descending' })
  const sorted = useMemo(() => sortTables(tables, sort.key, sort.dir), [tables, sort])
  const toggle = (key: SortKey) =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === 'descending' ? 'ascending' : s.key === key ? 'descending' : key === 'name' ? 'ascending' : 'descending' }))
  return (
    <div className="overflow-x-auto border border-border" tabIndex={0} role="region" aria-label={t('storage.tables')}>
      <table className="w-full border-collapse text-sm" data-testid="storage-table">
        <caption className="sr-only">{t('storage.tables')}</caption>
        <thead className="bg-surface-muted">
          <tr>
            {COLUMNS.map((c) => {
              const active = sort.key === c.key
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={active ? sort.dir : 'none'}
                  className={`px-2 py-0 font-normal ${c.key === 'name' ? 'text-left' : 'text-right'}`}
                >
                  <button
                    type="button"
                    className="inline-flex min-h-11 items-center gap-1 whitespace-nowrap text-fg-muted hover:text-fg"
                    onClick={() => toggle(c.key)}
                    data-testid={`sort-${c.key}`}
                  >
                    {t(c.label)}
                    {active && (sort.dir === 'ascending' ? <ArrowUp size={14} aria-hidden /> : <ArrowDown size={14} aria-hidden />)}
                  </button>
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((tb) => (
            <tr key={tb.name} className="border-t border-border" data-testid="storage-row" data-table={tb.name}>
              <th scope="row" className="whitespace-nowrap px-2 py-1.5 text-left font-normal">
                {tb.name}
              </th>
              <td className="whitespace-nowrap px-2 py-1.5 text-right">{fmtBytes(tb.total_bytes)}</td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right">{fmtBytes(tb.data_bytes)}</td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right">{fmtBytes(tb.index_bytes)}</td>
              <td className="whitespace-nowrap px-2 py-1.5 text-right" data-exact={tb.rows_exact}>
                {tb.rows_exact ? fmtNumber(tb.rows) : `${t('storage.estimated.mark')} ${fmtNumber(tb.rows)}`}
                {!tb.rows_exact && <span className="sr-only"> ({t('storage.estimated.sr')})</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Free space as a bar AND words (never colour alone). */
function DiskGauge({ d }: { d: StorageResponse['disk'] }) {
  const free = Math.max(0, Math.min(100, d.free_percent))
  return (
    <div className="flex flex-col gap-1" data-testid="disk-gauge">
      <div
        className="h-3 w-full border border-border-control"
        role="meter"
        aria-label={t('storage.disk.meter')}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={free}
        aria-valuetext={t('storage.disk.free', { pct: fmtNumber(free, 1) })}
      >
        <div className="h-full bg-accent-glow" style={{ width: `${100 - free}%` }} />
      </div>
      <span className="text-xs">
        {t('storage.disk.used', { used: fmtBytes(d.used_bytes), total: fmtBytes(d.total_bytes) })} ·{' '}
        <b>{t('storage.disk.free', { pct: fmtNumber(free, 1) })}</b>
      </span>
    </div>
  )
}

function kpis(d: StorageResponse): KpiSpec[] {
  return [
    {
      id: 'storage-db',
      label: t('storage.kpi.db'),
      value: fmtBytes(d.database_bytes),
      hint: t('storage.kpi.dbHint', { v: d.postgres_version }),
    },
    {
      id: 'storage-disk',
      label: t('storage.kpi.disk'),
      value: fmtBytes(d.disk.free_bytes),
      unit: t('storage.kpi.diskUnit'),
      hint: (
        <>
          <DiskGauge d={d.disk} />
          <span className="mt-1 block">{t('storage.disk.note')}</span>
        </>
      ),
    },
    {
      id: 'storage-growth',
      label: t('storage.kpi.growth'),
      value: d.growth.window_days === 0 ? '—' : `≈ ${fmtBytes(d.growth.bytes_per_year)}`,
      hint:
        d.growth.window_days === 0
          ? t('storage.growth.none')
          : t(d.growth.partial_history ? 'storage.growth.hintPartial' : 'storage.growth.hint', {
              days: fmtNumber(d.growth.window_days),
              month: fmtBytes(d.growth.bytes_per_month),
              records: fmtNumber(d.growth.records),
              samples: fmtNumber(d.growth.samples),
            }),
    },
  ]
}

export function StorageTab() {
  const q = useQuery(storageQuery())
  return (
    <div className="flex flex-col gap-3" data-testid="storage-tab">
      <Async query={q} skeleton={<SkeletonLines lines={4} />}>
        {(d) => (
          <>
            <KpiGrid items={kpis(d)} />
            <Panel title={t('storage.tables')} icon={Database} accent="glow" testId="panel-storage-tables">
              <p className="text-xs text-fg-muted">{t('storage.tables.note')}</p>
              <TablesTable tables={d.tables} />
            </Panel>
            <Panel title={t('storage.data')} icon={HardDrives} accent="glow" index={1} testId="panel-storage-data">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm" data-testid="storage-facts">
                <dt className="text-fg-muted">{t('storage.facts.live')}</dt>
                <dd>{fmtNumber(d.records_live)}</dd>
                <dt className="text-fg-muted">{t('storage.facts.deleted')}</dt>
                <dd data-testid="deleted-count">{fmtNumber(d.records_deleted)}</dd>
                <dt className="text-fg-muted">{t('storage.facts.first')}</dt>
                <dd>{d.first_data ? fmtDateTime(d.first_data) : '—'}</dd>
                <dt className="text-fg-muted">{t('storage.facts.last')}</dt>
                <dd>{d.last_data ? fmtDateTime(d.last_data) : '—'}</dd>
                <dt className="text-fg-muted">{t('storage.facts.ingest')}</dt>
                <dd>{d.last_ingest ? fmtDateTime(d.last_ingest) : '—'}</dd>
              </dl>
            </Panel>
            <Panel title={t('storage.limits')} icon={ListChecks} accent="glow" index={2} testId="panel-storage-limits">
              <ul className="list-disc space-y-1 pl-5 text-sm" data-testid="limits-list">
                {d.limits.items.map((item) => (
                  <li key={item.id} data-limit={item.id}>
                    {limitText(item)}
                  </li>
                ))}
              </ul>
            </Panel>
          </>
        )}
      </Async>
    </div>
  )
}
