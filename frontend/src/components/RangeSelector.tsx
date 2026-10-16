import { CaretLeft, CaretRight } from '@phosphor-icons/react'
import * as ToggleGroup from '@radix-ui/react-toggle-group'
import { useId } from 'react'
import { t } from '../i18n'
import { addDays, fmtDayLong, todayLocal } from '../lib/format'
import { MAX_CUSTOM_DAYS, PRESETS, type RangeInput, type RangePreset, type ResolvedRange, shiftRange } from '../lib/range'

interface Props {
  range: ResolvedRange
  onChange: (next: RangeInput) => void
}

const LABEL: Record<
  RangePreset,
  'range.24h' | 'range.7d' | 'range.30d' | 'range.90d' | 'range.1y' | 'range.all' | 'range.custom'
> = {
  '24h': 'range.24h',
  '7d': 'range.7d',
  '30d': 'range.30d',
  '90d': 'range.90d',
  '1y': 'range.1y',
  all: 'range.all',
  custom: 'range.custom',
}

/** Global interval selector (state lives in the URL, so every view is deep-linkable). */
export function RangeSelector({ range, onChange }: Props) {
  const fromId = useId()
  const toId = useId()
  const today = todayLocal()
  const prev = shiftRange(range, -1, today)
  const next = shiftRange(range, 1, today)
  const showWindow = range.preset !== 'custom' && range.preset !== 'all' && !range.current
  const arrow =
    'inline-flex min-h-11 min-w-11 items-center justify-center border border-border-control hover:bg-accent-glow/10 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent'
  return (
    <div className="flex flex-wrap items-center gap-3" data-testid="range-selector">
      <ToggleGroup.Root
        type="single"
        value={range.preset}
        onValueChange={(v) => {
          if (!v) return
          const preset = v as RangePreset
          onChange(
            preset === 'custom'
              ? { preset, from: range.from, to: range.to }
              : { preset },
          )
        }}
        aria-label={t('range.label')}
        className="inline-flex border border-border-control"
      >
        {PRESETS.map((p) => (
          <ToggleGroup.Item
            key={p}
            value={p}
            className="min-h-11 min-w-11 border-r border-border-control px-2 font-display text-sm uppercase tracking-wider last:border-r-0 data-[state=on]:bg-accent data-[state=on]:text-black hover:bg-accent-glow/10 data-[state=on]:hover:bg-accent"
          >
            {t(LABEL[p])}
          </ToggleGroup.Item>
        ))}
      </ToggleGroup.Root>
      {range.preset !== 'all' && (
        <div className="flex items-center gap-1" role="group" aria-label={t('range.label')}>
          <button
            type="button"
            className={arrow}
            aria-label={t('range.prev')}
            data-testid="range-prev"
            disabled={!prev}
            onClick={() => prev && onChange(prev)}
          >
            <CaretLeft size={20} aria-hidden />
          </button>
          <button
            type="button"
            className={arrow}
            aria-label={t('range.next')}
            data-testid="range-next"
            disabled={!next}
            onClick={() => next && onChange(next)}
          >
            <CaretRight size={20} aria-hidden />
          </button>
          {showWindow && (
            <span className="px-1 text-sm" data-testid="range-window">
              {range.days <= 1
                ? fmtDayLong(range.to)
                : t('range.window', { from: fmtDayLong(range.from), to: fmtDayLong(range.to) })}
            </span>
          )}
        </div>
      )}
      {range.preset === 'custom' && (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={fromId} className="hud-label">
            {t('range.from')}
          </label>
          <input
            id={fromId}
            type="date"
            className="input w-auto"
            value={range.from}
            max={range.to}
            min={addDays(range.to, -MAX_CUSTOM_DAYS + 1)}
            onChange={(e) => e.target.value && onChange({ preset: 'custom', from: e.target.value, to: range.to })}
          />
          <label htmlFor={toId} className="hud-label">
            {t('range.to')}
          </label>
          <input
            id={toId}
            type="date"
            className="input w-auto"
            value={range.to}
            min={range.from}
            max={today}
            onChange={(e) => e.target.value && onChange({ preset: 'custom', from: range.from, to: e.target.value })}
          />
        </div>
      )}
    </div>
  )
}
