import { Eye, EyeSlash, Heartbeat, SignIn, WarningOctagon } from '@phosphor-icons/react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { type FormEvent, useId, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { SessionInfo } from '../api/types'
import { t } from '../i18n'

function loginError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return t('login.error.credentials')
    if (err.status === 429) {
      const mins = Math.max(1, Math.ceil((err.retryAfter ?? 60) / 60))
      return t('login.error.locked', { minutes: mins })
    }
    if (err.status === 0) return t('state.error.network')
  }
  return t('state.error.generic')
}

/** Accessible login: visible labels, autofill hints for password managers, paste allowed. */
export function LoginPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const search = useSearch({ strict: false }) as { redirect?: string }
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [reveal, setReveal] = useState(false)
  const userId = useId()
  const passId = useId()
  const errId = useId()

  const login = useMutation({
    mutationFn: () => api<SessionInfo>('/api/v1/auth/login', { method: 'POST', body: { username, password } }),
    onSuccess: async (me) => {
      queryClient.setQueryData(['me'], me)
      const target = search.redirect && search.redirect.startsWith('/') ? search.redirect : '/'
      await navigate({ to: target as never })
    },
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!login.isPending) login.mutate()
  }

  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-8" id="main">
      <div className="hud-panel scanline w-full max-w-md overflow-hidden p-6">
        <div className="mb-6 flex items-center gap-3">
          <Heartbeat size={36} className="text-accent-glow" aria-hidden />
          <div>
            <h1 className="text-2xl uppercase tracking-widest">StatisticsByHeart</h1>
            <p className="hud-label">{t('login.subtitle')}</p>
          </div>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
          <div className="flex flex-col gap-1">
            <label htmlFor={userId} className="hud-label">
              {t('login.username')}
            </label>
            <input
              id={userId}
              name="username"
              type="text"
              className="input"
              autoComplete="username"
              autoCapitalize="none"
              spellCheck={false}
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              aria-describedby={login.isError ? errId : undefined}
            />
          </div>

          <div className="flex flex-col gap-1">
            <label htmlFor={passId} className="hud-label">
              {t('login.password')}
            </label>
            <div className="flex">
              <input
                id={passId}
                name="password"
                type={reveal ? 'text' : 'password'}
                className="input flex-1"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                aria-describedby={login.isError ? errId : undefined}
              />
              <button
                type="button"
                className="btn !border-l-0 px-3"
                aria-pressed={reveal}
                aria-label={reveal ? t('login.hide') : t('login.show')}
                onClick={() => setReveal((v) => !v)}
              >
                {reveal ? <EyeSlash size={20} aria-hidden /> : <Eye size={20} aria-hidden />}
              </button>
            </div>
          </div>

          {login.isError && (
            <p id={errId} role="alert" className="flex items-start gap-2 text-danger-text" data-testid="login-error">
              <WarningOctagon size={20} className="mt-0.5 shrink-0" aria-hidden />
              {loginError(login.error)}
            </p>
          )}

          <button type="submit" className="btn btn-primary" disabled={login.isPending}>
            <SignIn size={20} aria-hidden />
            {login.isPending ? t('login.submitting') : t('login.submit')}
          </button>
        </form>
      </div>
    </main>
  )
}
