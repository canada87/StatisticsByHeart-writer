import { ArrowsClockwise, Heartbeat, SignOut, SquaresFour } from '@phosphor-icons/react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { MotionConfig } from 'motion/react'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import { meQuery, syncStatusQuery } from '../api/queries'
import { t } from '../i18n'
import { timeAgo } from '../lib/format'
import { useRange } from '../lib/useRange'
import { RangeSelector } from './RangeSelector'

const NAV = [
  { to: '/', label: 'nav.overview', icon: SquaresFour },
  { to: '/sync', label: 'nav.sync', icon: ArrowsClockwise },
] as const

const HOUR = 3_600_000

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

function NavLinks({ variant }: { variant: 'side' | 'bottom' }) {
  const path = useRouterState({ select: (s) => s.location.pathname })
  return (
    <>
      {NAV.map(({ to, label, icon: Icon }) => {
        const active = to === '/' ? path === '/' : path.startsWith(to)
        return (
          <Link
            key={to}
            to={to}
            search={((prev: Record<string, unknown>) => ({ r: prev.r, from: prev.from, to: prev.to })) as never}
            aria-current={active ? 'page' : undefined}
            className={
              variant === 'side'
                ? `flex min-h-11 items-center gap-3 border-l-2 px-3 font-display uppercase tracking-wider ${
                    active ? 'border-accent-glow bg-accent-glow/10 text-fg' : 'border-transparent text-fg-muted hover:text-fg'
                  }`
                : `flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-xs uppercase tracking-wider ${
                    active ? 'text-accent-glow' : 'text-fg-muted'
                  }`
            }
          >
            <Icon size={variant === 'side' ? 20 : 24} weight={active ? 'fill' : 'regular'} aria-hidden />
            {t(label)}
          </Link>
        )
      })}
    </>
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
  return (
    <MotionConfig reducedMotion="user">
      <a
        href="#main"
        className="sr-only-focusable fixed left-2 top-2 z-50 border border-accent-glow bg-bg px-3 py-2"
      >
        {t('a11y.skip')}
      </a>

      {/* ≥1024px: fixed sidebar */}
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-60 flex-col gap-6 border-r border-border bg-bg/90 p-4 lg:flex">
        <div className="flex items-center gap-2 font-display text-base uppercase tracking-wider">
          <Heartbeat size={26} className="shrink-0 text-accent-glow" aria-hidden />
          <span className="min-w-0">StatisticsByHeart</span>
        </div>
        <nav aria-label={t('nav.main')} className="flex flex-col gap-1">
          <NavLinks variant="side" />
        </nav>
        <div className="mt-auto">
          <LogoutButton />
        </div>
      </aside>

      <div className="lg:pl-60">
        <header className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-border bg-bg/95 px-4 py-2">
          <div className="flex items-center gap-2 font-display uppercase tracking-widest lg:hidden">
            <Heartbeat size={22} className="text-accent-glow" aria-hidden />
            <span className="text-sm">SBH</span>
          </div>
          <RangeSelector range={range} onChange={setRange} />
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

      {/* <1024px: bottom navigation (top-level destinations only, icon + text) */}
      <nav
        aria-label={t('nav.main')}
        className="fixed inset-x-0 bottom-0 z-20 flex border-t border-border bg-bg/95 lg:hidden"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <NavLinks variant="bottom" />
      </nav>
    </MotionConfig>
  )
}
