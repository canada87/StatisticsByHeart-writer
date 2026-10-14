import type { Icon } from '@phosphor-icons/react'
import { motion } from 'motion/react'
import type { CSSProperties, ReactNode } from 'react'
import { useId } from 'react'

export type Accent = 'heart' | 'sleep' | 'activity' | 'energy' | 'vitals' | 'glow'

export const ACCENT_VAR: Record<Accent, string> = {
  heart: 'var(--color-m-heart)',
  sleep: 'var(--color-m-sleep-text)',
  activity: 'var(--color-m-activity)',
  energy: 'var(--color-m-energy)',
  vitals: 'var(--color-m-vitals)',
  glow: 'var(--color-accent-glow)',
}

interface PanelProps {
  title: string
  icon?: Icon
  accent?: Accent
  action?: ReactNode
  className?: string
  children: ReactNode
  /** Index for the staggered entrance (40-60 ms per element, transform/opacity only). */
  index?: number
  testId?: string
}

/** HUD panel: hairline border, corner brackets, uppercase technical label. */
export function Panel({ title, icon: IconCmp, accent = 'glow', action, className, children, index = 0, testId }: PanelProps) {
  const headingId = useId()
  return (
    <motion.section
      aria-labelledby={headingId}
      data-testid={testId}
      className={`hud-panel flex min-w-0 flex-col gap-3 ${className ?? ''}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.38, delay: Math.min(index, 8) * 0.05, ease: [0.22, 1, 0.36, 1] }}
      style={{ '--accent-c': ACCENT_VAR[accent] } as CSSProperties}
    >
      <header className="flex items-center justify-between gap-2">
        <h2 id={headingId} className="hud-label flex items-center gap-2">
          {IconCmp && <IconCmp size={18} weight="regular" aria-hidden style={{ color: 'var(--accent-c)' }} />}
          {title}
        </h2>
        {action}
      </header>
      {children}
    </motion.section>
  )
}

interface StatProps {
  value: string
  unit?: string
  label?: string
  size?: 'md' | 'lg'
  hint?: ReactNode
}

export function Stat({ value, unit, label, size = 'lg', hint }: StatProps) {
  return (
    <div className="min-w-0">
      {label && <div className="hud-label mb-1">{label}</div>}
      <div className="flex items-baseline gap-2">
        <span className={`hud-number ${size === 'lg' ? 'text-5xl' : 'text-3xl'}`}>{value}</span>
        {unit && <span className="text-sm text-fg-muted">{unit}</span>}
      </div>
      {hint && <div className="mt-1 text-xs text-fg-muted">{hint}</div>}
    </div>
  )
}

type Tone = 'ok' | 'warn' | 'danger' | 'muted'
const TONE_CLASS: Record<Tone, string> = {
  ok: 'text-ok border-ok',
  warn: 'text-warn border-warn',
  danger: 'text-danger-text border-danger-text',
  muted: 'text-fg-muted border-border-control',
}

/** Status pill. Colour is never the only carrier: always an icon and a text label. */
export function Badge({ tone, icon: IconCmp, children }: { tone: Tone; icon?: Icon; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 border px-2 py-0.5 text-xs ${TONE_CLASS[tone]}`}>
      {IconCmp && <IconCmp size={14} aria-hidden />}
      {children}
    </span>
  )
}

export function PageTitle({ children, sub }: { children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="mb-4">
      <h1 className="text-2xl uppercase tracking-widest">{children}</h1>
      {sub && <p className="mt-1 text-sm text-fg-muted">{sub}</p>}
    </div>
  )
}
