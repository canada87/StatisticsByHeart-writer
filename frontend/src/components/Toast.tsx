import { CheckCircle, X } from '@phosphor-icons/react'
import { type ReactNode, createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'
import { t } from '../i18n'

interface ToastAction {
  label: string
  onClick: () => void
}

interface ToastItem {
  id: number
  message: string
  action?: ToastAction
}

interface ToastApi {
  show: (message: string, action?: ToastAction) => void
}

const Ctx = createContext<ToastApi>({ show: () => {} })
export const useToast = (): ToastApi => useContext(Ctx)

const LIFETIME_MS = 12_000

/**
 * Success feedback with an optional action (Annulla). A polite live region: screen readers hear the
 * message, the button is a normal focusable control, and nothing disappears faster than 12 s.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)
  const dismiss = useCallback((id: number) => setItems((xs) => xs.filter((x) => x.id !== id)), [])
  const show = useCallback(
    (message: string, action?: ToastAction) => {
      const id = nextId.current++
      setItems((xs) => [...xs.slice(-2), { id, message, action }])
      setTimeout(() => dismiss(id), LIFETIME_MS)
    },
    [dismiss],
  )
  const api = useMemo(() => ({ show }), [show])
  return (
    <Ctx.Provider value={api}>
      {children}
      <div
        role="status"
        aria-live="polite"
        className="fixed inset-x-4 bottom-20 z-40 flex flex-col items-center gap-2 lg:inset-x-auto lg:bottom-6 lg:right-6 lg:items-end no-print"
        data-testid="toasts"
      >
        {items.map((it) => (
          <div
            key={it.id}
            className="flex w-full max-w-md items-center gap-3 border border-ok bg-surface px-3 py-2 shadow-lg"
            data-testid="toast"
          >
            <CheckCircle size={22} className="shrink-0 text-ok" aria-hidden />
            <span className="min-w-0 flex-1 text-sm">{it.message}</span>
            {it.action && (
              <button
                type="button"
                className="btn min-h-11 shrink-0 text-xs"
                data-testid="toast-action"
                onClick={() => {
                  it.action?.onClick()
                  dismiss(it.id)
                }}
              >
                {it.action.label}
              </button>
            )}
            <button
              type="button"
              className="btn min-h-11 min-w-11 shrink-0 px-2"
              aria-label={t('toast.close')}
              onClick={() => dismiss(it.id)}
            >
              <X size={18} aria-hidden />
            </button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
