import { ArrowLeft, EyeSlash, X } from '@phosphor-icons/react'
import * as Dialog from '@radix-ui/react-dialog'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { api } from '../api/client'
import { measuresQuery } from '../api/queries'
import type { ExcludeResult, MeasureItem } from '../api/types'
import { t } from '../i18n'
import { clampWindow, formatMeasure, measureTypeLabel } from '../lib/exclusions'
import { fmtDateTime, fmtDayLong } from '../lib/format'
import { useToast } from './Toast'
import { ErrorState, SkeletonLines } from './states'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  type: string
  from: string
  to: string
  /** Open straight on the confirmation of the measure that contains this record id. */
  preselectId?: number
  /** Offered when the list is limited to one chart point: show the whole chart range instead. */
  onWiden?: () => void
}

const periodText = (from: string, to: string) =>
  from === to ? fmtDayLong(from) : t('excl.period', { from: fmtDayLong(from), to: fmtDayLong(to) })

/**
 * Exclude a measure from every analysis. A chart point may aggregate many measures (a week, a month),
 * so the dialog always lists the single measures of the period and the user picks the one to exclude:
 * an aggregate is never excluded. Nothing is deleted; the measure can be restored from Sync / Dati.
 */
export function ExcludeDialog({ open, onOpenChange, type, from, to, preselectId, onWiden }: Props) {
  const win = clampWindow({ from, to })
  const list = useQuery(measuresQuery({ type, ...win }, open))
  const queryClient = useQueryClient()
  const toast = useToast()
  const reasonId = useId()
  const [chosen, setChosen] = useState<MeasureItem | 'list' | null>(null)
  const [reason, setReason] = useState('')

  const measures = list.data?.measures ?? []
  const auto =
    measures.length === 1
      ? measures[0]
      : preselectId !== undefined
        ? measures.find((m) => m.ids.includes(preselectId))
        : undefined
  const selected: MeasureItem | undefined = chosen === 'list' ? undefined : (chosen ?? auto)
  const canGoBack = measures.length > 1

  const undo = useMutation({
    mutationFn: (groupId: string) => api<void>(`/api/v1/exclusions/${groupId}`, { method: 'DELETE' }),
    onSuccess: () => {
      void queryClient.invalidateQueries()
      toast.show(t('excl.undone'))
    },
  })

  const exclude = useMutation({
    mutationFn: (m: MeasureItem) =>
      api<ExcludeResult>('/api/v1/exclusions', {
        method: 'POST',
        body: { record_id: m.ids[0], reason: reason.trim() || null },
      }),
    onSuccess: (res) => {
      void queryClient.invalidateQueries()
      onOpenChange(false)
      toast.show(
        t('excl.done', {
          what: formatMeasure(res.measure),
          date: fmtDayLong(res.measure.local_date),
        }),
        { label: t('excl.undo'), onClick: () => undo.mutate(res.group_id) },
      )
    },
  })

  const close = (o: boolean) => {
    if (!o) {
      setChosen(null)
      setReason('')
      exclude.reset()
    }
    onOpenChange(o)
  }

  return (
    <Dialog.Root open={open} onOpenChange={close}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/70" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[88dvh] w-[min(92vw,34rem)] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 overflow-y-auto border border-border-control bg-surface p-4"
          data-testid="exclude-dialog"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Dialog.Title className="font-display text-lg uppercase tracking-wider">
                {selected ? t('excl.confirm.title') : t('excl.list.title')}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-fg-muted">
                {measureTypeLabel(type)} · {periodText(win.from, win.to)}. {t('excl.explain')}
              </Dialog.Description>
            </div>
            <Dialog.Close className="btn min-h-11 min-w-11 shrink-0 px-2" aria-label={t('excl.close')}>
              <X size={20} aria-hidden />
            </Dialog.Close>
          </div>

          {list.isPending && <SkeletonLines lines={3} height="h-9" />}
          {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}

          {list.isSuccess && measures.length === 0 && (
            <p className="py-2 text-fg-muted" data-testid="exclude-empty">
              {t('excl.none')}
            </p>
          )}

          {list.isSuccess && measures.length > 1 && !selected && (
            <ul className="flex flex-col divide-y divide-border" data-testid="exclude-list">
              {measures.map((m) => (
                <li key={m.ids.join('-')} className="flex flex-wrap items-center justify-between gap-2 py-2" data-testid="exclude-measure">
                  <span className="min-w-0">
                    <span className="block">{formatMeasure(m)}</span>
                    <span className="block text-xs text-fg-muted">
                      {fmtDateTime(m.start)} · {m.sources.join(', ')}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="btn min-h-11 shrink-0 text-xs"
                    aria-label={t('excl.pick.aria', { what: formatMeasure(m), date: fmtDateTime(m.start) })}
                    onClick={() => setChosen(m)}
                  >
                    <EyeSlash size={16} aria-hidden />
                    {t('excl.pick')}
                  </button>
                </li>
              ))}
            </ul>
          )}

          {selected && (
            <div className="flex flex-col gap-3" data-testid="exclude-confirm">
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 border border-border p-3 text-sm">
                <dt className="text-fg-muted">{t('excl.col.type')}</dt>
                <dd data-testid="confirm-type">{measureTypeLabel(selected.type)}</dd>
                <dt className="text-fg-muted">{t('excl.col.date')}</dt>
                <dd data-testid="confirm-date">{fmtDateTime(selected.start)}</dd>
                <dt className="text-fg-muted">{t('excl.col.value')}</dt>
                <dd className="text-base" data-testid="confirm-value">
                  {formatMeasure(selected)}
                </dd>
                <dt className="text-fg-muted">{t('excl.col.sources')}</dt>
                <dd>{selected.sources.join(', ')}</dd>
              </dl>
              {selected.ids.length > 1 && <p className="text-xs text-fg-muted">{t('excl.copies', { n: selected.ids.length })}</p>}
              <div className="flex flex-col gap-1">
                <label htmlFor={reasonId} className="hud-label">
                  {t('excl.reason')}
                </label>
                <input
                  id={reasonId}
                  className="input"
                  maxLength={200}
                  value={reason}
                  placeholder={t('excl.reason.placeholder')}
                  onChange={(e) => setReason(e.target.value)}
                  data-testid="exclude-reason"
                />
              </div>
              {exclude.isError && <ErrorState error={exclude.error} onRetry={() => exclude.mutate(selected)} />}
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={exclude.isPending}
                  onClick={() => exclude.mutate(selected)}
                  data-testid="exclude-confirm-button"
                >
                  <EyeSlash size={20} aria-hidden />
                  {exclude.isPending ? t('excl.saving') : t('excl.confirm')}
                </button>
                {canGoBack && (
                  <button type="button" className="btn" onClick={() => setChosen('list')}>
                    <ArrowLeft size={18} aria-hidden />
                    {t('excl.back')}
                  </button>
                )}
                <Dialog.Close className="btn">{t('excl.cancel')}</Dialog.Close>
              </div>
            </div>
          )}

          {onWiden && !selected && (
            <button type="button" className="btn min-h-11 self-start text-xs" onClick={onWiden} data-testid="exclude-widen">
              {t('excl.widen')}
            </button>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
