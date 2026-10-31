import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExclusionItem, MeasureItem } from '../api/types'
import { makeRouter } from '../router'
import * as fx from './fixtures'
import * as fx2 from './fixtures2'

// Canvas is not available in jsdom: the chart is a stub with a button that "clicks" the 4th point,
// and it exposes every series name/option so the tests can check that nothing marks an exclusion.
vi.mock('../components/EChart', () => ({
  EChart: ({
    label,
    onPointClick,
    option,
  }: {
    label: string
    onPointClick?: (i: number) => void
    option?: { series?: { name: string; markPoint?: unknown; markLine?: unknown }[] }
  }) => (
    <div
      data-testid="echart-stub"
      data-series={(option?.series ?? []).map((s) => s.name).join('|')}
      data-marks={(option?.series ?? []).filter((s) => s.markPoint || s.markLine).length}
    >
      {label}
      {onPointClick && (
        <button type="button" data-testid="chart-click" onClick={() => onPointClick(3)}>
          click
        </button>
      )}
    </div>
  ),
}))

type Handler = (url: URL, init?: RequestInit) => { status?: number; body?: unknown }
let handlers: Record<string, Handler> = {}
let calls: { method: string; path: string; search: URLSearchParams; body: unknown }[] = []

const json = (body: unknown, status = 200) =>
  status === 204 ? new Response(null, { status }) : new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const measure = (over: Partial<MeasureItem> = {}): MeasureItem => ({
  ids: [11],
  type: 'Weight',
  start: '2026-10-12T05:10:00Z',
  end: null,
  local_date: '2026-10-12',
  value: 78,
  value2: null,
  unit: 'kg',
  label: null,
  sources: ['synthetic.scale'],
  ...over,
})
const foreign = measure({ ids: [12, 13], start: '2026-10-13T05:40:00Z', local_date: '2026-10-13', value: 32, sources: ['synthetic.phone', 'synthetic.scale'] })

const exclusion = (over: Partial<ExclusionItem> = {}): ExclusionItem => ({
  group_id: 'g1',
  type: 'Weight',
  start: '2026-10-13T05:40:00Z',
  end: null,
  local_date: '2026-10-13',
  value: 32,
  value2: null,
  unit: 'kg',
  label: null,
  sources: ['synthetic.phone', 'synthetic.scale'],
  reason: 'figlio, altro profilo',
  created_at: '2026-10-15T09:00:00Z',
  state: 'present',
  ...over,
})

beforeEach(() => {
  calls = []
  handlers = {
    '/api/v1/auth/me': () => ({ body: { username: 'admin', expires_at: '2026-10-22T00:00:00Z' } }),
    '/api/v1/sync/status': () => ({ body: fx.syncStatus }),
    '/api/v1/report': () => ({ body: fx2.report() }),
    '/api/v1/sleep/nights': () => ({ body: fx2.nights }),
    '/api/v1/exercise/sessions': () => ({ body: fx2.exercise }),
    '/api/v1/exercise/rules': () => ({ body: fx2.exerciseRules }),
    '/api/v1/measures': () => ({ body: { type: 'Weight', from: '', to: '', measures: [measure(), foreign] } }),
    '/api/v1/exclusions': (_u, init) =>
      init?.method === 'POST'
        ? {
            status: 201,
            body: {
              group_id: 'g1',
              records: 2,
              days: 1,
              measure: foreign,
            },
          }
        : { body: { items: [] } },
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://localhost')
      calls.push({
        method: init?.method ?? 'GET',
        path: url.pathname,
        search: url.searchParams,
        body: init?.body ? JSON.parse(String(init.body)) : null,
      })
      if (url.pathname.startsWith('/api/v1/exclusions/') && init?.method === 'DELETE') return json(null, 204)
      const direct = handlers[url.pathname]
      if (direct) {
        const r = direct(url, init)
        return json(r.body, r.status ?? 200)
      }
      const m = /^\/api\/v1\/metrics\/([^/]+)\/series$/.exec(url.pathname)
      if (m) return json(fx2.trendSeries(m[1] as string, [78, 78.2, 32, 78.4, 77.9, 78.1, 78]))
      return json({ error: { code: 'not_found', message: 'nope' } }, 404)
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

// the series fixtures are the days 9..15 October: pin the range to them (the clock is not fixed)
const RANGE_BODY = '/body?r=custom&from=2026-10-09&to=2026-10-15'

const measuresCalls = () => calls.filter((c) => c.path === '/api/v1/measures')

describe('excluding a measure from a chart', () => {
  it('the chart offers "Escludi un valore…" and lists the single measures of the period', async () => {
    renderApp(RANGE_BODY)
    const user = userEvent.setup()
    const chart = await screen.findByTestId('trend-weight')
    await user.click(await within(chart).findByTestId('exclude-open'))
    const dialog = await screen.findByTestId('exclude-dialog')
    expect(within(dialog).getByRole('heading', { name: 'Quale misura escludere?' })).toBeInTheDocument()
    expect(await within(dialog).findAllByTestId('exclude-measure')).toHaveLength(2)
    expect(dialog).toHaveTextContent('32 kg')
    expect(dialog).toHaveTextContent('synthetic.phone, synthetic.scale')
    expect(measuresCalls()[0]?.search.get('type')).toBe('Weight')
  })

  it('confirmation shows type, date and value; excluding sends the record and the reason, then offers Annulla', async () => {
    renderApp(RANGE_BODY)
    const user = userEvent.setup()
    await user.click(await within(await screen.findByTestId('trend-weight')).findByTestId('exclude-open'))
    const dialog = await screen.findByTestId('exclude-dialog')
    await user.click(await within(dialog).findByRole('button', { name: /Escludi la misura 32 kg/ }))

    const confirm = within(dialog).getByTestId('exclude-confirm')
    expect(within(confirm).getByTestId('confirm-type')).toHaveTextContent('Peso')
    expect(within(confirm).getByTestId('confirm-date')).toHaveTextContent('13/10')
    expect(within(confirm).getByTestId('confirm-value')).toHaveTextContent('32 kg')
    expect(confirm).toHaveTextContent('2 app')

    await user.type(within(confirm).getByLabelText('Motivo (facoltativo)'), 'figlio')
    await user.click(within(confirm).getByTestId('exclude-confirm-button'))

    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/api/v1/exclusions')).toBe(true))
    const post = calls.find((c) => c.method === 'POST')
    expect(post?.body).toEqual({ record_id: 12, reason: 'figlio' }) // a record, never an aggregate
    await waitFor(() => expect(screen.queryByTestId('exclude-dialog')).toBeNull())
    const toast = await screen.findByTestId('toast')
    expect(toast).toHaveTextContent('Escluso: 32 kg del')
    // every number on screen is refetched
    await waitFor(() => expect(calls.filter((c) => c.path.endsWith('/Weight/series')).length).toBeGreaterThan(1))

    // undo = restore, and says so
    await user.click(within(toast).getByTestId('toast-action'))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.path === '/api/v1/exclusions/g1')).toBe(true))
    expect(await screen.findByText(/Esclusione annullata/)).toBeInTheDocument()
  })

  it('a single measure goes straight to the confirmation', async () => {
    handlers['/api/v1/measures'] = () => ({ body: { type: 'Weight', from: '', to: '', measures: [foreign] } })
    renderApp(RANGE_BODY)
    const user = userEvent.setup()
    await user.click(await within(await screen.findByTestId('trend-weight')).findByTestId('exclude-open'))
    const dialog = await screen.findByTestId('exclude-dialog')
    expect(await within(dialog).findByTestId('exclude-confirm')).toBeInTheDocument()
    expect(within(dialog).queryByTestId('exclude-list')).toBeNull()
    expect(within(dialog).queryByRole('button', { name: 'Torna all’elenco' })).toBeNull()
  })

  it('clicking a chart point lists only the measures of that point (a day here)', async () => {
    renderApp(RANGE_BODY)
    const user = userEvent.setup()
    const chart = await screen.findByTestId('trend-weight')
    await user.click(await within(chart).findByTestId('chart-click')) // 4th point = 2026-10-12
    await screen.findByTestId('exclude-dialog')
    await waitFor(() => expect(measuresCalls().length).toBeGreaterThan(0))
    const c = measuresCalls().at(-1)
    expect(c?.search.get('from')).toBe('2026-10-12')
    expect(c?.search.get('to')).toBe('2026-10-12')
    // and the dialog can widen to the whole chart range
    await user.click(await screen.findByTestId('exclude-widen'))
    await waitFor(() => expect(measuresCalls().at(-1)?.search.get('from')).not.toBe('2026-10-12'))
  })

  it('a table row has its own "Escludi…" button, named after the row', async () => {
    renderApp(RANGE_BODY)
    const user = userEvent.setup()
    const chart = await screen.findByTestId('trend-weight')
    await user.click(await within(chart).findByRole('button', { name: 'Mostra tabella' }))
    const buttons = within(chart).getAllByTestId('exclude-row-button')
    expect(buttons).toHaveLength(7)
    expect(buttons[0]).toHaveAccessibleName(/^Escludi un valore: /)
    await user.click(buttons[0] as HTMLElement)
    await waitFor(() => expect(measuresCalls().at(-1)?.search.get('from')).toBe('2026-10-09'))
    expect(await screen.findByTestId('exclude-dialog')).toBeInTheDocument()
  })

  it('the dialog is a proper dialog: labelled, Escape closes it, nothing is sent', async () => {
    renderApp(RANGE_BODY)
    const user = userEvent.setup()
    await user.click(await within(await screen.findByTestId('trend-weight')).findByTestId('exclude-open'))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveAccessibleName('Quale misura escludere?')
    expect(dialog).toHaveAccessibleDescription(/Non viene cancellata/)
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('reports an error with a retry instead of closing', async () => {
    let fail = true
    handlers['/api/v1/exclusions'] = (_u, init) =>
      init?.method === 'POST'
        ? fail
          ? { status: 500, body: { error: { code: 'boom', message: 'Errore interno' } } }
          : { status: 201, body: { group_id: 'g1', records: 1, days: 1, measure: foreign } }
        : { body: { items: [] } }
    handlers['/api/v1/measures'] = () => ({ body: { type: 'Weight', from: '', to: '', measures: [foreign] } })
    renderApp(RANGE_BODY)
    const user = userEvent.setup()
    await user.click(await within(await screen.findByTestId('trend-weight')).findByTestId('exclude-open'))
    await user.click(await screen.findByTestId('exclude-confirm-button'))
    const alert = await screen.findByTestId('error-state')
    expect(alert).toHaveTextContent('Errore interno')
    fail = false
    await user.click(within(alert).getByRole('button', { name: 'Riprova' }))
    await waitFor(() => expect(screen.queryByTestId('exclude-dialog')).toBeNull())
  })

  it('says so when a period has no measure to exclude', async () => {
    handlers['/api/v1/measures'] = () => ({ body: { type: 'Weight', from: '', to: '', measures: [] } })
    renderApp(RANGE_BODY)
    const user = userEvent.setup()
    await user.click(await within(await screen.findByTestId('trend-weight')).findByTestId('exclude-open'))
    expect(await screen.findByTestId('exclude-empty')).toHaveTextContent('Nessuna misura escludibile')
  })

  it('the charts never mark or mention an exclusion (only the dedicated page does)', async () => {
    handlers['/api/v1/exclusions'] = () => ({ body: { items: [exclusion()] } })
    renderApp(RANGE_BODY)
    const chart = await screen.findByTestId('trend-weight')
    await within(chart).findByTestId('chart-summary')
    for (const panel of [chart, await screen.findByTestId('trend-systolic')]) {
      await within(panel).findByTestId('chart-summary')
      expect(panel.textContent).not.toMatch(/esclus[oaei]\b/i)
      const stub = within(panel).getByTestId('echart-stub')
      expect(stub).toHaveAttribute('data-marks', '0') // no markPoint / markLine anywhere
      expect(stub.getAttribute('data-series')).not.toMatch(/esclus/i)
    }
    expect(calls.some((c) => c.path === '/api/v1/exclusions')).toBe(false) // the charts do not even ask
  })
})

describe('which charts offer it', () => {
  it('weight, pressure, SpO2, resting heart rate, HRV and sleep do; steps and heart rate do not', async () => {
    renderApp('/heart')
    for (const id of ['restingHr', 'hrv', 'spo2']) {
      expect(await within(await screen.findByTestId(`trend-${id}`)).findByTestId('exclude-open')).toBeInTheDocument()
    }
    expect(within(await screen.findByTestId('trend-heartRate')).queryByTestId('exclude-open')).toBeNull()
  })

  it('the sleep page: duration chart and the per-night tables', async () => {
    renderApp('/sleep')
    const user = userEvent.setup()
    expect(await within(await screen.findByTestId('trend-sleep')).findByTestId('exclude-open')).toBeInTheDocument()
    const stages = await screen.findByTestId('chart-sleep-stages')
    await user.click(await within(stages).findByRole('button', { name: 'Mostra tabella' }))
    const rows = within(stages).getAllByTestId('exclude-row-button')
    expect(rows).toHaveLength(fx2.nights.nights.length)
    await user.click(rows[0] as HTMLElement)
    await waitFor(() => {
      const c = measuresCalls().at(-1)
      expect(c?.search.get('type')).toBe('SleepSession')
      expect(c?.search.get('from')).toBe(fx2.nights.nights[0]?.date)
    })
  })

  it('the activity page: every workout row can be excluded and opens on that very workout', async () => {
    handlers['/api/v1/measures'] = () => ({
      body: {
        type: 'ExerciseSession',
        from: '',
        to: '',
        measures: [
          measure({ ids: [1], type: 'ExerciseSession', value: 2100, unit: 's', label: 'Easy run', local_date: '2026-10-14', start: '2026-10-14T16:00:00Z' }),
          measure({ ids: [99], type: 'ExerciseSession', value: 1800, unit: 's', label: 'Walk', local_date: '2026-10-14', start: '2026-10-14T08:00:00Z' }),
        ],
      },
    })
    renderApp('/activity')
    const user = userEvent.setup()
    const rows = await screen.findAllByTestId('workout-row')
    await user.click(within(rows[0] as HTMLElement).getByTestId('exclude-row-button'))
    const confirm = await screen.findByTestId('exclude-confirm') // straight to the confirmation of id 1
    expect(within(confirm).getByTestId('confirm-value')).toHaveTextContent('Easy run · 35 min')
    expect(within(confirm).getByTestId('confirm-type')).toHaveTextContent('Allenamenti')
  })
})

describe('the "Dati esclusi" tab', () => {
  it('lists type, date, value, source, reason and when it was excluded', async () => {
    handlers['/api/v1/exclusions'] = () => ({
      body: {
        items: [
          exclusion(),
          exclusion({ group_id: 'g2', type: 'BloodPressure', value: 190, value2: 120, unit: 'mmHg', reason: null, state: 'deleted_in_hc', sources: ['synthetic.watch'] }),
          exclusion({ group_id: 'g3', start: null, local_date: null, value: null, state: 'missing', sources: [] }),
        ],
      },
    })
    renderApp('/sync?tab=excluded')
    const rows = await screen.findAllByTestId('excluded-row')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveTextContent('Peso')
    expect(rows[0]).toHaveTextContent('32 kg')
    expect(rows[0]).toHaveTextContent('synthetic.phone, synthetic.scale')
    expect(rows[0]).toHaveTextContent('figlio, altro profilo')
    expect(rows[0]).toHaveTextContent('15/10') // excluded on
    expect(rows[0]).toHaveAttribute('data-state', 'present')
    expect(rows[1]).toHaveTextContent('190/120 mmHg')
    expect(rows[1]).toHaveTextContent('Cancellata in Health Connect') // text, not just colour
    expect(rows[2]).toHaveTextContent('Non più archiviata')
    expect(within(rows[0] as HTMLElement).getByRole('button', { name: /Ripristina Peso/ })).toBeInTheDocument()
  })

  it('"Ripristina" removes the exclusion, refreshes everything and confirms', async () => {
    handlers['/api/v1/exclusions'] = () => ({ body: { items: [exclusion()] } })
    renderApp('/sync?tab=excluded')
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('restore-button'))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.path === '/api/v1/exclusions/g1')).toBe(true))
    expect(await screen.findByText(/Ripristinato: Peso 32 kg/)).toBeInTheDocument()
  })

  it('explains how to exclude when there is nothing excluded', async () => {
    renderApp('/sync?tab=excluded')
    const empty = await screen.findByTestId('empty-state')
    expect(empty).toHaveTextContent('Nessun dato escluso')
    expect(empty).toHaveTextContent('Escludi un valore…')
  })

  it('is a tab of Sync / Dati and shows in the URL', async () => {
    const { router } = renderApp('/sync')
    await userEvent.setup().click(await screen.findByRole('tab', { name: 'Dati esclusi' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ tab: 'excluded' }))
  })
})
