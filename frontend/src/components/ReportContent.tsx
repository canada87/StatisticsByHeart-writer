import { ListChecks } from '@phosphor-icons/react'
import { useId } from 'react'
import { SECTION_DEFS, type IsOn } from '../lib/reportSections'
import { t } from '../i18n'

interface Props {
  isOn: IsOn
  onToggle: (id: string, on: boolean) => void
  onReset: () => void
  loading: boolean
  saveFailed: boolean
}

/** "Contenuto del report": which sections and measures appear on screen and in the PDF. */
export function ReportContentPanel({ isOn, onToggle, onReset, loading, saveFailed }: Props) {
  const uid = useId()
  const groups = [
    { id: 'sections', title: t('report.sel.sections') },
    { id: 'metrics', title: t('report.sel.metrics') },
  ] as const
  return (
    <details className="hud-panel p-3 no-print" data-testid="report-content">
      <summary className="flex min-h-11 cursor-pointer items-center gap-2 font-display text-sm uppercase tracking-wider">
        <ListChecks size={20} aria-hidden />
        {t('report.sel.title')}
      </summary>
      <p className="mt-1 text-sm text-fg-muted">{t('report.sel.intro')}</p>
      <div className="mt-2 grid gap-4 sm:grid-cols-2">
        {groups.map((g) => (
          <fieldset key={g.id} className="min-w-0" disabled={loading}>
            <legend className="hud-label mb-1">{g.title}</legend>
            <ul className="flex flex-col">
              {SECTION_DEFS.filter((d) => d.group === g.id).map((d) => {
                const id = `${uid}-${d.id}`
                return (
                  <li key={d.id}>
                    <label htmlFor={id} className="flex min-h-11 cursor-pointer items-center gap-2">
                      <input
                        id={id}
                        type="checkbox"
                        data-testid={`sel-${d.id}`}
                        className="size-5 accent-[var(--color-accent)]"
                        checked={isOn(d.id)}
                        onChange={(e) => onToggle(d.id, e.target.checked)}
                      />
                      {t(d.label)}
                    </label>
                  </li>
                )
              })}
            </ul>
          </fieldset>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <button type="button" className="btn" onClick={onReset} data-testid="sel-reset" disabled={loading}>
          {t('report.sel.reset')}
        </button>
        <span className="text-xs text-fg-muted">{t('report.sel.saved')}</span>
        {saveFailed && (
          <span role="alert" className="text-xs text-danger-text" data-testid="sel-save-error">
            {t('report.sel.saveFailed')}
          </span>
        )}
      </div>
      <p className="mt-2 text-xs text-fg-muted">{t('report.sel.csvNote')}</p>
    </details>
  )
}
