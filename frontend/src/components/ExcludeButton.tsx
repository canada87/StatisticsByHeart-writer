import { EyeSlash } from '@phosphor-icons/react'
import { useState } from 'react'
import { t } from '../i18n'
import { ExcludeDialog } from './ExcludeDialog'

interface Props {
  type: string
  from: string
  to: string
  /** What the button is about, for the accessible name ("Escludi un valore: 14/10/2026"). */
  label: string
  preselectId?: number
}

/** A table-row button that opens the exclusion dialog for one period (or one known record). */
export function ExcludeButton({ type, from, to, label, preselectId }: Props) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        className="btn min-h-11 text-xs"
        aria-label={t('excl.row.aria', { what: label })}
        data-testid="exclude-row-button"
        onClick={() => setOpen(true)}
      >
        <EyeSlash size={16} aria-hidden />
        {t('excl.row')}
      </button>
      {open && <ExcludeDialog open onOpenChange={setOpen} type={type} from={from} to={to} preselectId={preselectId} />}
    </>
  )
}
