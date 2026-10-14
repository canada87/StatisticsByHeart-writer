import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeRouter } from '../router'
import * as fx from './fixtures'

// Canvas is not available in jsdom: the chart wrapper is replaced by a stub.
vi.mock('../components/EChart', () => ({
  EChart: ({ label }: { label: string }) => <div data-testid="echart-stub">{label}</div>,
}))

type Handler = (url: URL, init?: RequestInit) => { status?: number; body?: unknown }
let handlers: Record<string, Handler> = {}
let calls: { url: string; method: string }[] = []

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const unauth = () => ({ status: 401, body: { error: { code: 'not_authenticated', message: 'Login required' } } })

beforeEach(() => {
  calls = []
  handlers = {
    '/api/v1/auth/me': () => ({ body: { username: 'admin', expires_at: '2026-10-22T00:00:00Z' } }),
    '/api/v1/summary/today': () => ({ body: fx.summary }),
    '/api/v1/metrics/Steps/series': () => ({
      body: fx.series('Steps', [10400, 5200, 8300, 9100, 10200, 10700, 10200]),
    }),
    '/api/v1/metrics/RestingHeartRate/series': () => ({
      body: fx.series('RestingHeartRate', [59, 57, 57, 59, 57, 57, 56]),
    }),
    '/api/v1/sync/status': () => ({ body: fx.syncStatus }),
    '/api/v1/data/inventory': () => ({ body: fx.inventory }),
    '/api/v1/data/reconciliation': () => ({ body: fx.reconciliation }),
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost')
      calls.push({ url: url.pathname, method: init?.method ?? 'GET' })
      const h = handlers[url.pathname]
      if (!h) return json({ error: { code: 'not_found', message: 'nope' } }, 404)
      const r = h(url, init)
      return json(r.body, r.status ?? 200)
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderApp(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } })
  const router = makeRouter(queryClient, createMemoryHistory({ initialEntries: [path] }))
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, queryClient }
}

describe('login', () => {
  it('redirects unauthenticated visitors to the login form', async () => {
    handlers['/api/v1/auth/me'] = unauth
    renderApp('/sync')
    expect(await screen.findByLabelText('Nome utente')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toHaveAttribute('autocomplete', 'current-password')
  })

  it('shows an alert for wrong credentials and allows reveal/paste', async () => {
    handlers['/api/v1/auth/me'] = unauth
    handlers['/api/v1/auth/login'] = () => ({
      status: 401,
      body: { error: { code: 'invalid_credentials', message: 'bad' } },
    })
    renderApp('/login')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Nome utente'), 'admin')
    await user.click(screen.getByLabelText('Password'))
    await user.paste('segreta')
    expect(screen.getByLabelText('Password')).toHaveValue('segreta')
    await user.click(screen.getByRole('button', { name: 'Mostra password' }))
    expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'text')
    await user.click(screen.getByRole('button', { name: 'Accedi' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('non corretti')
    expect(calls.find((c) => c.url === '/api/v1/auth/login')?.method).toBe('POST')
  })

  it('announces the lockout with minutes to wait', async () => {
    handlers['/api/v1/auth/me'] = unauth
    handlers['/api/v1/auth/login'] = () => ({
      status: 429,
      body: { error: { code: 'too_many_attempts', message: 'slow' } },
    })
    renderApp('/login')
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Nome utente'), 'admin')
    await user.type(screen.getByLabelText('Password'), 'x')
    await user.click(screen.getByRole('button', { name: 'Accedi' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Troppi tentativi')
  })
})

describe('overview', () => {
  it('shows skeletons first, then the numbers', async () => {
    renderApp('/')
    expect(await screen.findAllByRole('status', { name: 'Caricamento…' })).not.toHaveLength(0)
    expect(await screen.findByTestId('steps-value')).toHaveTextContent('10.200')
    const sleep = screen.getByTestId('panel-sleep')
    expect(sleep).toHaveTextContent('6 h 34 min')
    expect(within(sleep).getByTestId('sleep-stages')).toHaveTextContent('Profondo')
    expect(screen.getByTestId('panel-heart')).toHaveTextContent('60')
    expect(screen.getByTestId('activities')).toHaveTextContent('Camminata')
    expect(screen.getByTestId('panel-energy')).toHaveTextContent('Calcolato dai record')
  })

  it('every chart has a text summary and a table alternative', async () => {
    renderApp('/')
    const user = userEvent.setup()
    const summaries = await screen.findAllByTestId('chart-summary')
    expect(summaries[0]).toHaveTextContent(/Passi: 7 valori \(giorno\)\. Totale 64\.100/)
    const [toggle] = await screen.findAllByRole('button', { name: 'Mostra tabella' })
    await user.click(toggle as HTMLElement)
    const table = await screen.findByRole('table', { name: /Tabella dati: Passi/ })
    expect(within(table).getAllByRole('row')).toHaveLength(8)
  })

  it('shows an error with a retry button, then recovers', async () => {
    let fail = true
    handlers['/api/v1/summary/today'] = () =>
      fail ? { status: 500, body: { error: { code: 'boom', message: 'Errore interno' } } } : { body: fx.summary }
    renderApp('/')
    const alerts = await screen.findAllByTestId('error-state')
    expect(alerts[0]).toHaveTextContent('Errore interno')
    fail = false
    await userEvent.setup().click(within(alerts[0] as HTMLElement).getByRole('button', { name: 'Riprova' }))
    await waitFor(() => expect(screen.getByTestId('steps-value')).toHaveTextContent('10.200'))
  })

  it('handles an empty database with friendly empty states', async () => {
    handlers['/api/v1/summary/today'] = () => ({ body: fx.emptySummary })
    handlers['/api/v1/metrics/Steps/series'] = () => ({ body: fx.series('Steps', [null, null, null]) })
    renderApp('/')
    expect(await screen.findByText('Nessuna notte registrata')).toBeInTheDocument()
    expect(screen.getByText('Nessuna attività registrata')).toBeInTheDocument()
    expect((await screen.findAllByText('Nessun dato nell’intervallo')).length).toBeGreaterThan(0)
    expect(screen.getByTestId('steps-value')).toHaveTextContent('—')
  })

  it('keeps the global range in the URL', async () => {
    const { router } = renderApp('/')
    const user = userEvent.setup()
    await user.click(await screen.findByRole('radio', { name: '30g' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ r: '30d' }))
    await user.click(screen.getByRole('radio', { name: '7g' }))
    await waitFor(() => expect(router.state.location.search).not.toHaveProperty('r'))
  })
})

describe('sync / dati', () => {
  it('lists runs with refused records and Reader errors', async () => {
    renderApp('/sync')
    const run = await screen.findByTestId('sync-run')
    expect(run).toHaveTextContent('Parziale')
    expect(run).toHaveTextContent('Xiaomi test')
    expect(run).toHaveTextContent('Steps · invalid_record')
    expect(run).toHaveTextContent('type_read_failed')
    expect(run).toHaveTextContent('value: out of range')
  })

  it('inventory shows per-type and per-source counts', async () => {
    renderApp('/sync?tab=inventory')
    expect(await screen.findAllByTestId('source-card')).toHaveLength(2)
    const row = await screen.findByTestId('type-row')
    expect(row).toHaveTextContent('synthetic.watch')
    expect(screen.getByTestId('inv-totals')).toHaveTextContent('120 record')
  })

  it('reconciliation highlights the double-counting risk next to the official value', async () => {
    renderApp('/sync?tab=recon')
    const row = await screen.findByTestId('recon-row')
    expect(row).toHaveTextContent('10.200')
    expect(row).toHaveTextContent('20.056')
    expect(row).toHaveTextContent('Sovrapposizione')
    expect(row).toHaveTextContent('Coincide')
    expect(row).toHaveTextContent('synthetic.watch')
    expect(await screen.findByTestId('chart-summary')).toHaveTextContent('1 coincidono')
  })

  it('switching tabs updates the URL', async () => {
    const { router } = renderApp('/sync')
    await userEvent.setup().click(await screen.findByRole('tab', { name: 'Inventario' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ tab: 'inventory' }))
  })
})
