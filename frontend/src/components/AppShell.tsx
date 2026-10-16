import {
  ArrowsClockwise,
  Barbell,
  DotsThree,
  FileText,
  Heartbeat,
  Moon,
  Scales,
  SignOut,
  SquaresFour,
} from '@phosphor-icons/react'
import * as Popover from '@radix-ui/react-popover'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { MotionConfig } from 'motion/react'
import { type ReactNode, useState } from 'react'
import { api } from '../api/client'
import { meQuery, syncStatusQuery } from '../api/queries'
import { t } from '../i18n'
import { timeAgo } from '../lib/format'
import { useRange } from '../lib/useRange'
import { RangeSelector } from './RangeSelector'

const NAV = [
  { to: '/', label: 'nav.overview', icon: SquaresFour },
  { to: '/heart', label: 'nav.heart', icon: Heartbeat },
  { to: '/sleep', label: 'nav.sleep', icon: Moon },
  { to: '/activity', label: 'nav.activity', icon: Barbell },
  { to: '/body', label: 'nav.body', icon: Scales },
  { to: '/report', label: 'nav.report', icon: FileText },
  { to: '/sync', label: 'nav.sync', icon: ArrowsClockwise },
] as const

/** Bottom nav shows at most 4 destinations + "Altro" with the rest (PROJECT_GUIDE 8.7). */
const BOTTOM_MAIN = NAV.slice(0, 4)
const BOTTOM_MORE = NAV.slice(4)

const HOUR = 3_600_000
const keepRange = ((prev: Record<string, unknown>) => ({ r: prev.r, from: prev.from, to: prev.to, end: prev.end })) as never

function isActive(path: string, to: string): boolean {
  return to === '/' ? path === '/' : path.startsWith(to)
}

/** "Link status": how long ago the phone last synced. Text + icon + colour, never colour alone. */
export function LinkStatus() {
  const q = useQuery(syncStatusQuery())
  const last = q.data?.last_success_at ?? null
  const age = last ? Date.now() - new Date(last).getTime() : Infinity
  const state = q.isError ? 'error' : age < 3 * HOUR ? 'ok' : age < 24 * HOUR ? 'warn' : 'stale'
  const text = q.isPending
    ? t('link.checking')
    : q.isError
      ? t('link.unknown')
      : last
        ? t('link.last', { when: timeAgo(last) })
        : t('link.never')
  const color = { ok: 'text-ok', warn: 'text-warn', stale: 'text-danger-text', error: 'text-fg-muted' }[state]
  return (
    <div className={`flex items-center gap-2 text-sm ${color}`} data-testid="link-status" data-state={state}>
      <span className={state === 'ok' ? 'live-dot' : 'h-2 w-2 rounded-full bg-current'} aria-hidden />
      <span className="hud-label !text-current">{t('link.title')}</span>
      <span>{text}</span>
    </div>
  )
}

function SideLinks() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  return (
    <>
      {NAV.map(({ to, label, icon: Icon }) => {
        const active = isActive(path, to)
        return (
          <Link
            key={to}
            to={to}
            search={keepRange}
            aria-current={active ? 'page' : undefined}
            className={`flex min-h-11 items-center gap-3 border-l-2 px-3 font-display uppercase tracking-wider ${
              active ? 'border-accent-glow bg-accent-glow/10 text-fg' : 'border-transparent text-fg-muted hover:text-fg'
            }`}
          >
            <Icon size={20} weight={active ? 'fill' : 'regular'} aria-hidden />
            {t(label)}
          </Link>
        )
      })}
    </>
  )
}

const bottomItem = (active: boolean) =>
  `flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-xs uppercase tracking-wider ${
    active ? 'text-accent-glow' : 'text-fg-muted'
  }`

function BottomNav() {
  const path = useRouterState({ select: (s) => s.location.pathname })
  const [open, setOpen] = useState(false)
  const moreActive = BOTTOM_MORE.some((n) => isActive(path, n.to))
  return (
    <nav
      aria-label={t('nav.main')}
      className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-bg/95 lg:hidden"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {BOTTOM_MAIN.map(({ to, label, icon: Icon }) => {
        const active = isActive(path, to)
        return (
          <Link key={to} to={to} search={keepRange} aria-current={active ? 'page' : undefined} className={bottomItem(active)}>
            <Icon size={24} weight={active ? 'fill' : 'regular'} aria-hidden />
            {t(label)}
          </Link>
        )
      })}
      <Popover.Root open={open} onOpenChange={setOpen}>
        <Popover.Trigger className={bottomItem(moreActive || open)} aria-label={t('nav.more.aria')} data-testid="nav-more">
          <DotsThree size={24} weight="bold" aria-hidden />
          {t('nav.more')}
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            side="top"
            align="end"
            sideOffset={8}
            className="z-30 w-56 border border-border-control bg-surface p-1"
            data-testid="nav-more-menu"
          >
            {BOTTOM_MORE.map(({ to, label, icon: Icon }) => {
              const active = isActive(path, to)
              return (
                <Link
                  key={to}
                  to={to}
                  search={keepRange}
                  aria-current={active ? 'page' : undefined}
                  onClick={() => setOpen(false)}
                  className={`flex min-h-12 items-center gap-3 px-3 font-display uppercase tracking-wider ${
                    active ? 'bg-accent-glow/10 text-fg' : 'text-fg-muted hover:text-fg'
                  }`}
                >
                  <Icon size={22} weight={active ? 'fill' : 'regular'} aria-hidden />
                  {t(label)}
                </Link>
              )
            })}
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </nav>
  )
}

function LogoutButton({ compact = false }: { compact?: boolean }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const me = useQuery(meQuery())
  const logout = useMutation({
    mutationFn: () => api<void>('/api/v1/auth/logout', { method: 'POST' }),
    onSettled: () => {
      queryClient.clear()
      void navigate({ to: '/login', search: {} as never })
    },
  })
  return (
    <button
      type="button"
      className="btn w-full justify-start"
      onClick={() => logout.mutate()}
      disabled={logout.isPending}
      aria-label={compact ? t('auth.logout') : undefined}
    >
      <SignOut size={20} aria-hidden />
      {!compact && (
        <span className="flex min-w-0 flex-col items-start text-left leading-tight">
          <span>{t('auth.logout')}</span>
          {me.data && <span className="truncate text-xs normal-case tracking-normal text-fg-muted">{me.data.username}</span>}
        </span>
      )}
    </button>
  )
}

export function AppShell({ children }: { children?: ReactNode }) {
  const [range, setRange] = useRange()
  const path = useRouterState({ select: (s) => s.location.pathname })
  // The report has its own period chooser: the global range would only confuse.
  const showRange = !path.startsWith('/report')
  return (
    <MotionConfig reducedMotion="user">
      <a href="#main" className="sr-only-focusable fixed left-2 top-2 z-50 border border-accent-glow bg-bg px-3 py-2">
        {t('a11y.skip')}
      </a>

      {/* The sidebar column stretches over the whole page height (background + border); its content sticks. */}
      <div className="app-grid lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
        <aside className="hidden border-r border-border bg-bg/90 lg:block">
          <div className="sticky top-0 flex h-dvh flex-col gap-6 p-4">
            <div className="flex items-center gap-2 font-display text-base uppercase tracking-wider">
              <Heartbeat size={26} className="shrink-0 text-accent-glow" aria-hidden />
              <span className="min-w-0">StatisticsByHeart</span>
            </div>
            <nav aria-label={t('nav.main')} className="flex flex-col gap-1">
              <SideLinks />
            </nav>
            <div className="mt-auto">
              <LogoutButton />
            </div>
          </div>
        </aside>

        <div className="min-w-0">
          <header
            data-app-header
            className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border bg-bg/95 px-4 py-2"
          >
            <div className="flex items-center gap-2 font-display uppercase tracking-widest lg:hidden">
              <Heartbeat size={22} className="text-accent-glow" aria-hidden />
              <span className="text-sm">SBH</span>
            </div>
            {showRange ? <RangeSelector range={range} onChange={setRange} /> : <span />}
            <div className="flex items-center gap-3">
              <LinkStatus />
              <div className="lg:hidden">
                <LogoutButton compact />
              </div>
            </div>
          </header>

          <main id="main" tabIndex={-1} className="min-h-dvh px-4 pb-24 pt-4 outline-none lg:pb-8">
            {children ?? <Outlet />}
          </main>
        </div>
      </div>

      <BottomNav />
    </MotionConfig>
  )
}
