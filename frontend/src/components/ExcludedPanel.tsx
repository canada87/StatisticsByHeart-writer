import { ArrowCounterClockwise, EyeSlash, Warning } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { exclusionsQuery } from '../api/queries'
import type { ExclusionItem } from '../api/types'
import { type MessageKey, t } from '../i18n'
import { formatMeasure, measureTypeLabel } from '../lib/exclusions'
import { fmtDateTime } from '../lib/format'
import { Badge, Panel } from './hud'
import { useToast } from './Toast'
import { Async, ErrorState, SkeletonLines } from './states'

function RestoreButton({ item }: { item: ExclusionItem }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const what = `${measureTypeLabel(item.type)} ${formatMeasure(item)}`
  const restore = useMutation({
    mutationFn: () => api<void>(`/api/v1/exclusions/${item.group_id}`, { method: 'DELETE' }),
    onSuccess: () => {
      void queryClient.invalidateQueries()
      toast.show(t('excl.restored', { what }))
    },
  })
  return (
    <div className="flex flex-col items-start gap-1">
      <button
        type="button"
        className="btn min-h-11 text-xs"
        disabled={restore.isPending}
        aria-label={t('excl.restore.aria', { what, date: item.start ? fmtDateTime(item.start) : '' })}
        data-testid="restore-button"
        onClick={() => restore.mutate()}
      >
        <ArrowCounterClockwise size={16} aria-hidden />
        {restore.isPending ? t('excl.saving') : t('excl.restore')}
      </button>
      {restore.isError && <ErrorState error={restore.error} onRetry={() => restore.mutate()} />}
    </div>
  )
}

const th = 'whitespace-nowrap px-2 py-1.5 text-left font-normal text-fg-muted'
const td = 'px-2 py-1.5'

/** "Dati esclusi": the only place where exclusions are visible (charts never mark them). */
export function ExcludedPanel() {
  const q = useQuery(exclusionsQuery())
  return (
    <Panel title={t('excl.page.title')} icon={EyeSlash} accent="glow" testId="panel-excluded">
      <p className="text-sm text-fg-muted">{t('excl.page.intro')}</p>
      <Async
        query={q}
        skeleton={<SkeletonLines lines={4} height="h-9" />}
        isEmpty={(d) => d.items.length === 0}
        emptyTitle={t('excl.page.empty')}
        emptyHint={t('excl.page.emptyHint')}
      >
        {(d) => (
          <div className="overflow-x-auto border border-border" tabIndex={0} role="region" aria-label={t('excl.page.title')}>
            <table className="w-full border-collapse text-sm" data-testid="excluded-table">
              <caption className="sr-only">{t('excl.page.title')}</caption>
              <thead className="bg-surface-muted">
                <tr>
                  <th scope="col" className={th}>
                    {t('excl.col.type')}
                  </th>
                  {/* the action comes second: on a phone the rest of the row scrolls, the button must not */}
                  <th scope="col" className={th}>
                    {t('excl.col.action')}
                  </th>
                  {(['excl.col.date', 'excl.col.value', 'excl.col.sources', 'excl.col.reason', 'excl.col.excludedOn', 'excl.col.state'] as const).map((k) => (
                    <th key={k} scope="col" className={th}>
                      {t(k)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {d.items.map((it) => (
                  <tr key={it.group_id} className="border-t border-border align-top" data-testid="excluded-row" data-state={it.state}>
                    <th scope="row" className={`${td} whitespace-nowrap text-left font-normal`}>
                      {measureTypeLabel(it.type)}
                    </th>
                    <td className={td}>
                      <RestoreButton item={it} />
                    </td>
                    <td className={`${td} whitespace-nowrap`}>{it.start ? fmtDateTime(it.start) : '—'}</td>
                    <td className={`${td} whitespace-nowrap`} data-testid="excluded-value">
                      {formatMeasure(it)}
                    </td>
                    <td className={td}>{it.sources.length ? it.sources.join(', ') : '—'}</td>
                    <td className={td}>{it.reason ?? '—'}</td>
                    <td className={`${td} whitespace-nowrap`}>{fmtDateTime(it.created_at)}</td>
                    <td className={td}>
                      {it.state === 'present' ? (
                        t('excl.state.present')
                      ) : (
                        <Badge tone="warn" icon={Warning}>
                          {t(`excl.state.${it.state}` as MessageKey)}
                        </Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Async>
    </Panel>
  )
}
