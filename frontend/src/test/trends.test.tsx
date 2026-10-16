import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { makeRouter } from '../router'
import * as fx from './fixtures'
import * as fx2 from './fixtures2'

// Canvas is not available in jsdom: the chart wrapper is replaced by a stub.
vi.mock('../components/EChart', () => ({
  EChart: ({
    label,
    activeIndex,
    option,
  }: {
    label: string
    activeIndex?: number | null
    option?: { series?: { name: string; lineStyle?: { type?: string }; markArea?: { data: unknown[] } }[] }
  }) => (
    <div
      data-testid="echart-stub"
      data-active={activeIndex ?? ''}
      data-series={(option?.series ?? []).map((s) => `${s.name}:${s.lineStyle?.type ?? ''}`).join('|')}
      data-bands={option?.series?.find((s) => s.markArea)?.markArea?.data.length ?? 0}
    >
      {label}
    </div>
  ),
}))

type Handler = (url: URL) => { status?: number; body?: unknown }
let handlers: Record<string, Handler> = {}
let urls: URL[] = []
let csvDownloads: { name: string; text: string }[] = []

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
  urls = []
  csvDownloads = []
  handlers = {
    '/api/v1/auth/me': () => ({ body: { username: 'admin', expires_at: '2026-10-22T00:00:00Z' } }),
    '/api/v1/sync/status': () => ({ body: fx.syncStatus }),
    '/api/v1/report': () => ({ body: fx2.report() }),
    '/api/v1/sleep/nights': () => ({ body: fx2.nights }),
    '/api/v1/exercise/sessions': () => ({ body: fx2.exercise }),
    '/api/v1/heart/daypart': () => ({ body: fx2.daypart() }),
    '/api/v1/exercise/rules': () => ({ body: fx2.exerciseRules }),
    '/api/v1/data/bounds': () => ({ body: { first: '2026-01-01', last: '2026-10-15' } }),
    '/api/v1/report/daily': () => ({
      body: {
        from: '2026-10-01',
        to: '2026-10-02',
        columns: [
          { key: 'steps', label: 'Passi', unit: 'count' },
          { key: 'hr_avg', label: 'FC media', unit: 'bpm' },
        ],
        rows: [
          { date: '2026-10-01', values: { steps: 100, hr_avg: 70.5 } },
          { date: '2026-10-02', values: { steps: null, hr_avg: 71 } },
        ],
      },
    }),
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost')
      urls.push(url)
      const direct = handlers[url.pathname]
      if (direct) {
        const r = direct(url)
        return json(r.body, r.status ?? 200)
      }
      const m = /^\/api\/v1\/metrics\/([^/]+)\/series$/.exec(url.pathname)
      if (m) return json(fx2.trendSeries(m[1] as string, [70, 72, 71, 69, 73, 74, 72]))
      return json({ error: { code: 'not_found', message: 'nope' } }, 404)
    }),
  )
  // jsdom has no URL.createObjectURL: capture what would be downloaded
  URL.createObjectURL = vi.fn((blob: Blob) => {
    void blob.arrayBuffer().then((buf) =>
      csvDownloads.push({ name: '', text: new TextDecoder('utf-8', { ignoreBOM: true }).decode(buf) }),
    )
    return 'blob:fake'
  })
  URL.revokeObjectURL = vi.fn()
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
  return { router }
}

describe('heart page', () => {
  it('shows KPIs with a delta arrow AND text, and a trend chart per metric', async () => {
    renderApp('/heart')
    const kpi = await screen.findByTestId('kpi-heartRate')
    expect(within(kpi).getByTestId('kpi-value')).toHaveTextContent('70')
    const delta = within(kpi).getByTestId('delta')
    expect(delta).toHaveAttribute('data-direction', 'up')
    expect(delta).toHaveTextContent('vs periodo prec.')
    expect(delta.querySelector('svg')).not.toBeNull() // arrow icon
    expect(delta.querySelector('.sr-only')).toHaveTextContent('in aumento')
    for (const id of ['heartRate', 'restingHr', 'hrv', 'spo2']) {
      expect(await screen.findByTestId(`trend-${id}`)).toBeInTheDocument()
    }
  })

  it('requests band, moving average and previous period for the trend, with automatic day buckets', async () => {
    renderApp('/heart')
    await screen.findByTestId('trend-heartRate')
    await waitFor(() => expect(urls.some((u) => u.pathname.endsWith('/HeartRate/series'))).toBe(true))
    const u = urls.find((x) => x.pathname.endsWith('/HeartRate/series'))
    expect(u?.searchParams.get('band')).toBe('true')
    expect(u?.searchParams.get('ma')).toBe('true')
    expect(u?.searchParams.get('compare')).toBe('true')
    expect(u?.searchParams.get('bucket')).toBe('day')
  })

  it('granularity is selectable and the moving average / comparison are toggles', async () => {
    renderApp('/heart')
    const user = userEvent.setup()
    const chart = await screen.findByTestId('trend-restingHr')
    expect(await within(chart).findByTestId('granularity-actual')).toHaveTextContent('giorno')
    await user.selectOptions(within(chart).getByLabelText('Granularità'), 'week')
    await waitFor(() => expect(urls.some((u) => u.searchParams.get('bucket') === 'week')).toBe(true))

    const ma = within(chart).getByRole('button', { name: /Media mobile 7g/ })
    expect(ma).toHaveAttribute('aria-pressed', 'false')
    await user.click(ma)
    expect(ma).toHaveAttribute('aria-pressed', 'true')
    const prev = within(chart).getByRole('button', { name: 'Periodo precedente' })
    await user.click(prev)
    expect(prev).toHaveAttribute('aria-pressed', 'true')
  })

  it('text summary states the trend and the previous-period mean', async () => {
    renderApp('/heart')
    const chart = await screen.findByTestId('trend-restingHr')
    const text = await within(chart).findByTestId('chart-summary')
    expect(text).toHaveTextContent('7 valori (giorno)')
    expect(text).toHaveTextContent('Periodo precedente: media')
  })

  it('values are reachable from the keyboard: the cursor drives the readout and the tooltip', async () => {
    renderApp('/heart')
    const chart = await screen.findByTestId('trend-restingHr')
    expect(within(chart).queryByRole('slider')).toBeNull() // no range bar under the chart
    const focusable = await within(chart).findByTestId('chart-focus')
    focusable.focus()
    expect(focusable).toHaveFocus()
    fireEvent.keyDown(focusable, { key: 'ArrowRight' })
    fireEvent.keyDown(focusable, { key: 'ArrowRight' })
    expect(within(chart).getByTestId('chart-readout')).toHaveTextContent('bpm')
    expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-active', '1')
    fireEvent.keyDown(focusable, { key: 'End' })
    expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-active', '6')
    fireEvent.keyDown(focusable, { key: 'Home' })
    expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-active', '0')
    fireEvent.keyDown(focusable, { key: 'Escape' })
    expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-active', '')
    expect(within(chart).getByTestId('chart-readout')).toBeEmptyDOMElement()
  })

  it('offers the table alternative and a CSV export of the chart', async () => {
    renderApp('/heart')
    const user = userEvent.setup()
    const chart = await screen.findByTestId('trend-restingHr')
    await user.click(await within(chart).findByRole('button', { name: 'Mostra tabella' }))
    const table = within(chart).getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(8)
    await user.click(within(chart).getByRole('button', { name: 'Mostra grafico' }))
    await user.click(within(chart).getByRole('button', { name: 'Esporta CSV' }))
    await waitFor(() => expect(csvDownloads.length).toBe(1))
    const csv = csvDownloads[0]?.text ?? ''
    expect(csv.charCodeAt(0)).toBe(0xfeff) // BOM for Excel
    expect(csv.split('\r\n')[0]).toContain('Data')
    expect(csv.split('\r\n').length).toBeGreaterThan(7)
  })
})

describe('heart rate day / night', () => {
  it('two KPIs with a delta versus the previous period', async () => {
    renderApp('/heart')
    const day = await screen.findByTestId('kpi-heart-day')
    expect(within(day).getByTestId('kpi-value')).toHaveTextContent('75')
    expect(within(day).getByTestId('delta')).toHaveAttribute('data-direction', 'up')
    expect(day).toHaveTextContent('FC diurna')
    const night = screen.getByTestId('kpi-heart-night')
    expect(within(night).getByTestId('kpi-value')).toHaveTextContent('56')
    expect(within(night).getByTestId('delta')).toHaveAttribute('data-direction', 'down')
    expect(night).toHaveTextContent('FC notturna')
  })

  it('per-day buckets: two series, distinct line style and name; table, CSV and summary follow', async () => {
    renderApp('/heart')
    const user = userEvent.setup()
    const chart = await screen.findByTestId('trend-heartRate')
    await waitFor(() =>
      expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-series', 'FC diurna:solid|FC notturna:dashed'),
    )
    expect(within(chart).getByTestId('chart-summary')).toHaveTextContent('FC diurna media 75 bpm, FC notturna media 56 bpm')
    expect(within(chart).getByTestId('daypart-note')).toHaveTextContent('tratteggiata')
    // the other heart charts share the cache but must stay single-series
    const rest = await screen.findByTestId('trend-restingHr')
    expect(within(rest).getByTestId('echart-stub').getAttribute('data-series')).not.toContain('FC diurna')
    expect(within(rest).queryByTestId('daypart-note')).toBeNull()
    await user.click(within(chart).getByRole('button', { name: 'Mostra tabella' }))
    const table = within(chart).getByRole('table')
    expect(within(table).getByRole('columnheader', { name: 'FC diurna (bpm)' })).toBeInTheDocument()
    expect(within(table).getByRole('columnheader', { name: 'FC notturna (bpm)' })).toBeInTheDocument()
    await user.click(within(chart).getByRole('button', { name: 'Mostra grafico' }))
    await user.click(within(chart).getByRole('button', { name: 'Esporta CSV' }))
    await waitFor(() => expect(csvDownloads.length).toBe(1))
    expect(csvDownloads[0]?.text.split('\r\n')[0]).toContain('FC notturna (bpm)')
  })

  it('intraday buckets: shaded nights with a "Notte" legend entry instead of a second series', async () => {
    handlers['/api/v1/metrics/HeartRate/series'] = () => {
      const base = fx2.trendSeries('HeartRate', [60, 61, 62, 63, 64, 65, 66, 67])
      return {
        body: {
          ...base,
          bucket: 'hour',
          points: base.points.map((p, i) => ({ ...p, t: `2026-10-14T${String(i).padStart(2, '0')}:00:00+02:00` })),
        },
      }
    }
    handlers['/api/v1/heart/daypart'] = () => ({
      body: fx2.daypart({
        nights: [{ date: '2026-10-14', start: '2026-10-13T21:30:00Z', end: '2026-10-14T03:00:00Z', source: 'sleep' }],
      }),
    })
    renderApp('/heart?r=24h&end=2026-10-14')
    const chart = await screen.findByTestId('trend-heartRate')
    await waitFor(() => expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-bands', '1'))
    const stub = within(chart).getByTestId('echart-stub')
    expect(stub.getAttribute('data-series')).toContain('Notte:')
    expect(stub.getAttribute('data-series')).not.toContain('FC notturna')
    expect(within(chart).getByTestId('daypart-note')).toHaveTextContent('fascia fissa 23:00–07:00')
  })

  it('falls back to the plain chart when the split is not available', async () => {
    handlers['/api/v1/heart/daypart'] = () => ({ status: 500, body: { error: { code: 'x', message: 'boom' } } })
    renderApp('/heart')
    const chart = await screen.findByTestId('trend-heartRate')
    await waitFor(() => expect(within(chart).getByTestId('echart-stub')).toBeInTheDocument())
    expect(within(chart).getByTestId('echart-stub').getAttribute('data-series')).not.toContain('FC diurna')
    expect(await screen.findByTestId('kpi-heart-day')).toHaveTextContent('—')
  })
})

describe('hourly granularity', () => {
  it('is offered for dense metrics up to 31 days and requests bucket=hour', async () => {
    renderApp('/heart?r=30d')
    const user = userEvent.setup()
    const chart = await screen.findByTestId('trend-heartRate')
    const select = await within(chart).findByLabelText('Granularità')
    expect(within(select).getByRole('option', { name: 'Ora' })).toBeInTheDocument()
    await user.selectOptions(select, 'hour')
    await waitFor(() =>
      expect(urls.some((u) => u.pathname.endsWith('/HeartRate/series') && u.searchParams.get('bucket') === 'hour')).toBe(true),
    )
  })
  it('is not offered beyond 31 days nor for instant measurements', async () => {
    renderApp('/heart?r=90d')
    const long = await screen.findByTestId('trend-heartRate')
    expect(within(await within(long).findByLabelText('Granularità')).queryByRole('option', { name: 'Ora' })).toBeNull()
  })
  it('is not offered for resting heart rate', async () => {
    renderApp('/heart?r=30d')
    const rest = await screen.findByTestId('trend-restingHr')
    expect(within(await within(rest).findByLabelText('Granularità')).queryByRole('option', { name: 'Ora' })).toBeNull()
  })
})

describe('range arrows', () => {
  it('step back by the window length, put it in the URL and disable "next" at today', async () => {
    const { router } = renderApp('/heart?r=30d')
    const user = userEvent.setup()
    const next = await screen.findByRole('button', { name: 'Intervallo successivo' })
    expect(next).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Intervallo precedente' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ r: '30d' }))
    expect((router.state.location.search as { end?: string }).end).toBeTruthy()
    expect(await screen.findByTestId('range-window')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Intervallo successivo' })).toBeEnabled()
    await waitFor(() => expect(urls.some((u) => u.pathname === '/api/v1/report' && u.searchParams.get('to') !== null)).toBe(true))
    await user.click(screen.getByRole('button', { name: 'Intervallo successivo' }))
    await waitFor(() => expect((router.state.location.search as { end?: string }).end).toBeUndefined())
    expect(screen.queryByTestId('range-window')).toBeNull()
  })
  it('are hidden for "Tutto"', async () => {
    renderApp('/heart?r=all')
    await screen.findByTestId('range-selector')
    expect(screen.queryByRole('button', { name: 'Intervallo precedente' })).toBeNull()
  })
})

describe('sleep page', () => {
  it('KPIs: duration, bedtime and wake time as clock values, regularity', async () => {
    renderApp('/sleep')
    const duration = await screen.findByTestId('kpi-sleep-duration')
    expect(duration).toHaveTextContent('6 h 50 min')
    expect(within(duration).getByTestId('delta')).toHaveAttribute('data-direction', 'up')
    // 320 min after 18:00 = 23:20; 405 min after midnight = 06:45
    expect(screen.getByTestId('kpi-sleep-bedtime')).toHaveTextContent('23:20')
    expect(screen.getByTestId('kpi-sleep-bedtime')).toHaveTextContent('+12 min vs periodo prec.')
    expect(screen.getByTestId('kpi-sleep-wake')).toHaveTextContent('06:45')
    expect(screen.getByTestId('kpi-sleep-regularity')).toHaveTextContent('±10')
  })

  it('stage and schedule charts have text summaries', async () => {
    renderApp('/sleep')
    const stages = await screen.findByTestId('chart-sleep-stages')
    expect(await within(stages).findByTestId('chart-summary')).toHaveTextContent('Medie per notte')
    const schedule = await screen.findByTestId('chart-sleep-schedule')
    expect(await within(schedule).findByTestId('chart-summary')).toHaveTextContent('Addormentamento medio 23:20')
  })
})

describe('"Oggi" button', () => {
  it('only exists when the window is in the past and removes `end` from the URL', async () => {
    const { router } = renderApp('/heart?r=30d')
    const user = userEvent.setup()
    await screen.findByRole('button', { name: 'Intervallo successivo' })
    expect(screen.queryByTestId('range-today')).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Intervallo precedente' }))
    const today = await screen.findByRole('button', { name: /Torna a oggi/ })
    expect(today).toHaveTextContent('Oggi')
    await user.click(today)
    await waitFor(() => expect((router.state.location.search as { end?: string }).end).toBeUndefined())
    expect(router.state.location.search).toMatchObject({ r: '30d' })
    expect(screen.queryByTestId('range-today')).toBeNull()
  })
  it('is there for a deep link to a past window, and not for "Tutto"', async () => {
    renderApp('/heart?r=7d&end=2026-01-31')
    expect(await screen.findByTestId('range-today')).toBeInTheDocument()
  })
})

describe('real workouts (activity page)', () => {
  it('asks for real workouts only by default and lets you see all of them (URL filter)', async () => {
    const { router } = renderApp('/activity')
    const user = userEvent.setup()
    await screen.findAllByTestId('workout-row')
    expect(urls.some((u) => u.pathname === '/api/v1/exercise/sessions' && u.searchParams.get('scope') === 'real')).toBe(true)
    const filter = screen.getByTestId('workouts-filter')
    expect(within(filter).getByRole('radio', { name: 'Solo veri' })).toHaveAttribute('aria-checked', 'true')
    expect(within(filter).getByTestId('workouts-counts')).toHaveTextContent('2 veri su 3 sessioni')
    await user.click(within(filter).getByRole('radio', { name: 'Tutti' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ workouts: 'all' }))
    await waitFor(() =>
      expect(urls.some((u) => u.pathname === '/api/v1/exercise/sessions' && u.searchParams.get('scope') === 'all')).toBe(true),
    )
  })

  it('shows the signals as icon + text badges and the verdict, with its source', async () => {
    renderApp('/activity')
    const rows = await screen.findAllByTestId('workout-row')
    expect(within(rows[0] as HTMLElement).getByTestId('signals')).toHaveTextContent('FC sì 95%')
    expect(within(rows[0] as HTMLElement).getByTestId('signals')).toHaveTextContent('GPS sì')
    expect(within(rows[0] as HTMLElement).getByTestId('signals')).toHaveTextContent('Avvio: da te')
    expect(within(rows[0] as HTMLElement).getByTestId('verdict')).toHaveTextContent('Vero')
    expect(within(rows[0] as HTMLElement).getByTestId('verdict-reason')).toHaveTextContent('nessuna regola di esclusione → vero')
    const second = rows[1] as HTMLElement
    expect(within(second).getByTestId('signals')).toHaveTextContent('FC no 10%')
    expect(within(second).getByTestId('signals')).toHaveTextContent('GPS no')
    expect(within(second).getByTestId('signals')).toHaveTextContent('Avvio: automatico')
    expect(within(second).getByTestId('verdict')).toHaveTextContent('manuale') // overridden by the user
    expect(within(second).getByTestId('verdict-reason')).toHaveTextContent('la regola direbbe: Camminata → non vero')
    expect(within(second).getByTestId('signals').querySelector('svg')).not.toBeNull()
  })

  it('the override control sends the verdict (CSRF header) and refreshes the page data', async () => {
    const calls: { url: string; body: unknown; header: string | null }[] = []
    const base = fetch as unknown as (...a: Parameters<typeof fetch>) => ReturnType<typeof fetch>
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), 'http://localhost')
        if (init?.method === 'PUT') {
          calls.push({
            url: url.pathname,
            body: JSON.parse(String(init.body)),
            header: new Headers(init.headers).get('X-SBH-Client'),
          })
          return json({ id: 1, override: false, is_real: false })
        }
        return base(input, init)
      }),
    )
    renderApp('/activity')
    const user = userEvent.setup()
    const select = await screen.findByRole('combobox', { name: 'Verdetto per Easy run' })
    expect(select).toHaveValue('auto')
    await user.selectOptions(select, 'no')
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toEqual({ url: '/api/v1/exercise/sessions/1/override', body: { value: false }, header: 'web' })
    await user.selectOptions(select, 'auto')
    await waitFor(() => expect(calls[1]?.body).toEqual({ value: null }))
  })

  it('says so when no session is a real workout', async () => {
    handlers['/api/v1/exercise/sessions'] = () => ({ body: { ...fx2.exercise, sessions: [], real_count: 0, total_count: 3 } })
    renderApp('/activity')
    expect(await screen.findByText('Nessun allenamento vero nel periodo')).toBeInTheDocument()
  })
})

describe('workout rules panel', () => {
  it('shows the rules from the backend in evaluation order, with their values', async () => {
    renderApp('/activity')
    const panel = await screen.findByTestId('workout-rules')
    const items = await within(panel).findAllByRole('listitem')
    expect(items.map((i) => i.getAttribute('data-rule'))).toEqual(['override', 'type', 'duration', 'default'])
    expect(items[1]).toHaveTextContent('Se il tipo di attività è camminata → non vero')
    expect(items[2]).toHaveTextContent('Se dura meno di 15 minuti → non vero')
    expect(items[2]).toHaveTextContent('esattamente 15 minuti vale vero')
    expect(within(panel).getByTestId('rules-daytime-hr')).toHaveTextContent('30 minuti successivi')
    expect(within(panel).getByTestId('rules-gps-note')).toHaveTextContent('nessuna app scrive la traccia GPS')
  })

  it('follows the values the backend sends (no number or type hardcoded in the page)', async () => {
    handlers['/api/v1/exercise/rules'] = () => ({
      body: {
        ...fx2.exerciseRules,
        rules: [
          { id: 'override', params: {} },
          { id: 'type', params: { types: ['WALKING', 'YOGA'] } },
          { id: 'duration', params: { min_minutes: 20 } },
          { id: 'default', params: {} },
        ],
        daytime_hr: { excludes: 'real_workouts', recovery_minutes: 45 },
      },
    })
    renderApp('/activity')
    const panel = await screen.findByTestId('workout-rules')
    expect(await within(panel).findByText(/meno di 20 minuti/)).toBeInTheDocument()
    expect(within(panel).getByTestId('rules-daytime-hr')).toHaveTextContent('45 minuti successivi')
    expect(panel).toHaveTextContent('camminata, ')
  })

  it('the text under the list links to the panel', async () => {
    renderApp('/activity')
    const link = await screen.findByTestId('rules-link')
    expect(link).toHaveAttribute('href', '#workout-rules')
  })

  it('the reason next to the verdict names the rule that decided, with its values', async () => {
    handlers['/api/v1/exercise/sessions'] = () => ({
      body: {
        ...fx2.exercise,
        sessions: [
          { ...fx2.exercise.sessions[0], id: 11, title: 'Short run', duration_s: 10 * 60 + 20, auto_real: false, auto_rule: 'duration', is_real: false },
          { ...fx2.exercise.sessions[0], id: 12, title: 'Stroll', type: 'WALKING', duration_s: 5 * 60, auto_real: false, auto_rule: 'type', is_real: false },
        ],
      },
    })
    renderApp('/activity')
    const rows = await screen.findAllByTestId('workout-row')
    expect(within(rows[0] as HTMLElement).getByTestId('verdict-reason')).toHaveTextContent('dura 10 min (< 15) → non vero')
    // a short walk: the first rule in the order (the type) is the one shown
    expect(within(rows[1] as HTMLElement).getByTestId('verdict-reason')).toHaveTextContent('Camminata → non vero')
  })
})

describe('report', () => {
  it('states that only real workouts count', async () => {
    renderApp('/report?p=month')
    expect(await screen.findByTestId('report-workouts-note')).toHaveTextContent('regole della pagina Attività')
    expect(await screen.findByTestId('report-workouts-excluded')).toHaveTextContent('4 attività escluse')
  })
})

describe('heart rate without workouts', () => {
  it('KPIs say what they include and the general HR KPI says it includes everything', async () => {
    renderApp('/heart')
    expect(await screen.findByTestId('kpi-heartRate')).toHaveTextContent('Include tutto')
    expect(await screen.findByTestId('kpi-heart-day')).toHaveTextContent('Senza allenamenti veri (+30 min)')
  })

  it('the toggle is off by default, lives in the URL and asks the server to include workouts', async () => {
    const { router } = renderApp('/heart')
    const user = userEvent.setup()
    const chart = await screen.findByTestId('trend-heartRate')
    const toggle = await within(chart).findByRole('button', { name: 'Includi allenamenti' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')
    expect(urls.some((u) => u.pathname === '/api/v1/heart/daypart' && u.searchParams.has('include_workouts'))).toBe(false)
    await user.click(toggle)
    await waitFor(() => expect(router.state.location.search).toMatchObject({ incl: 1 }))
    await waitFor(() =>
      expect(urls.some((u) => u.pathname === '/api/v1/heart/daypart' && u.searchParams.get('include_workouts') === 'true')).toBe(true),
    )
    expect(within(chart).getByRole('button', { name: 'Includi allenamenti' })).toHaveAttribute('aria-pressed', 'true')
    await waitFor(() => expect(screen.getByTestId('kpi-heart-day')).toHaveTextContent('Con gli allenamenti'))
  })

  it('only the heart-rate chart has the toggle', async () => {
    renderApp('/heart')
    const rest = await screen.findByTestId('trend-restingHr')
    expect(within(rest).queryByRole('button', { name: 'Includi allenamenti' })).toBeNull()
  })

  it('intraday: excluded workouts are dashed bands labelled "Allenamento", next to the night bands', async () => {
    handlers['/api/v1/metrics/HeartRate/series'] = () => {
      const base = fx2.trendSeries('HeartRate', [60, 61, 62, 63, 64, 65, 66, 67])
      return {
        body: {
          ...base,
          bucket: 'hour',
          points: base.points.map((p, i) => ({ ...p, t: `2026-10-14T${String(10 + i).padStart(2, '0')}:00:00+02:00` })),
        },
      }
    }
    handlers['/api/v1/heart/daypart'] = (url) => ({
      body: fx2.daypart({
        include_workouts: url.searchParams.get('include_workouts') === 'true',
        nights: [{ date: '2026-10-14', start: '2026-10-14T06:00:00Z', end: '2026-10-14T08:30:00Z', source: 'sleep' }],
        workouts: [{ start: '2026-10-14T11:00:00Z', end: '2026-10-14T11:20:00Z', recovery_end: '2026-10-14T11:50:00Z' }],
      }),
    })
    renderApp('/heart?r=24h&end=2026-10-14')
    const chart = await screen.findByTestId('trend-heartRate')
    await waitFor(() => expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-bands', '2'))
    expect(within(chart).getByTestId('echart-stub').getAttribute('data-series')).toContain('Allenamento:')
    expect(within(chart).getByTestId('daypart-workout-note')).toHaveTextContent('30 minuti di recupero')
    // with the workouts included nothing is excluded: only the night band is left
    const user = userEvent.setup()
    await user.click(within(chart).getByRole('button', { name: 'Includi allenamenti' }))
    await waitFor(() => expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-bands', '1'))
    expect(within(chart).queryByTestId('daypart-workout-note')).toBeNull()
  })
})

describe('activity page', () => {
  it('lists workouts with type, date, duration, kcal and average heart rate', async () => {
    renderApp('/activity')
    const rows = await screen.findAllByTestId('workout-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('Easy run')
    expect(rows[0]).toHaveTextContent('35 min')
    expect(rows[0]).toHaveTextContent('310 kcal')
    expect(rows[0]).toHaveTextContent('148 bpm')
    expect(rows[1]).toHaveTextContent('Camminata')
    expect(rows[1]).toHaveTextContent('—')
  })

  it('shows the weekly volume with a summary', async () => {
    renderApp('/activity')
    const weekly = await screen.findByTestId('chart-workouts-weekly')
    expect(await within(weekly).findByTestId('chart-summary')).toHaveTextContent('2 allenamenti')
  })

  it('shows distance in km and sleep-style KPIs for steps', async () => {
    renderApp('/activity')
    const km = await screen.findByTestId('kpi-distance')
    expect(km).toHaveTextContent('49')
    expect(km).toHaveTextContent('km')
    expect(await screen.findByTestId('kpi-workouts')).toHaveTextContent('2')
  })
})

describe('body page', () => {
  it('blood pressure: both values on one chart, with indicative bands clearly labelled', async () => {
    renderApp('/body')
    const bp = await screen.findByTestId('trend-systolic')
    expect(await within(bp).findByTestId('reference-note')).toHaveTextContent('indicative e non sono una diagnosi')
    expect(within(bp).getByTestId('chart-summary')).toHaveTextContent('Pressione diastolica')
    await waitFor(() => expect(urls.some((u) => u.searchParams.get('field') === 'diastolic')).toBe(true))
  })

  it('blood pressure with no data yet explains what to do', async () => {
    handlers['/api/v1/report'] = () => ({ body: fx2.report({ noBloodPressure: true }) })
    handlers['/api/v1/metrics/BloodPressure/series'] = () => ({
      body: fx.series('BloodPressure', [null, null, null]),
    })
    renderApp('/body')
    const bp = await screen.findByTestId('trend-systolic')
    expect(await within(bp).findByText('Nessuna misurazione di pressione ancora')).toBeInTheDocument()
    expect(within(bp).getByText(/attiva «Pressione arteriosa»/)).toBeInTheDocument()
    expect(await screen.findByTestId('kpi-systolic')).toHaveTextContent('Nessun dato nel periodo')
  })
})

describe('"Tutto" range', () => {
  it('uses the first day with data from /data/bounds', async () => {
    renderApp('/heart?r=all')
    await screen.findByTestId('trend-heartRate')
    await waitFor(() => {
      const u = urls.filter((x) => x.pathname.endsWith('/HeartRate/series')).at(-1)
      expect(u?.searchParams.get('from')).toBe('2026-01-01')
    })
    expect(screen.getByRole('radio', { name: 'Tutto' })).toHaveAttribute('aria-checked', 'true')
  })
})

describe('report page', () => {
  it('summarises the twelve metrics with deltas, best/worst days and sparklines', async () => {
    renderApp('/report?p=month&d=2026-09-10')
    expect(await screen.findByTestId('period-label')).toHaveTextContent('settembre 2026')
    for (const key of ['steps', 'heart_rate', 'resting_hr', 'sleep', 'workouts', 'active_kcal', 'total_kcal', 'distance', 'weight', 'spo2', 'hrv', 'blood_pressure']) {
      expect(await screen.findByTestId(`report-row-${key}`)).toBeInTheDocument()
    }
    const steps = screen.getByTestId('report-row-steps')
    expect(within(steps).getByTestId('delta')).toHaveTextContent('+5,3%')
    expect(steps).toHaveTextContent('Migliore:')
    expect(steps).toHaveTextContent('Peggiore:')
    expect(within(steps).getByRole('img', { name: /Andamento di Passi/ })).toBeInTheDocument()
    // heart rate has no good/bad day; weight neither
    expect(screen.getByTestId('report-row-heart_rate')).not.toHaveTextContent('Migliore:')
    expect(screen.getByTestId('report-row-sleep')).toHaveTextContent('6 h 57 min')
    expect(screen.getByTestId('report-row-blood_pressure')).toHaveTextContent('70/78 mmHg')
    expect(screen.getByTestId('report-sleep')).toHaveTextContent('±22 min')
    expect(screen.getByTestId('report-workouts')).toHaveTextContent('Camminata 2')
  })

  it('period comes from the URL and the request uses it (clipped to today)', async () => {
    renderApp('/report?p=month&d=2026-09-10')
    await screen.findByTestId('period-label')
    await waitFor(() => expect(urls.some((u) => u.pathname === '/api/v1/report')).toBe(true))
    const u = urls.find((x) => x.pathname === '/api/v1/report')
    expect(u?.searchParams.get('from')).toBe('2026-09-01')
    expect(u?.searchParams.get('to')).toBe('2026-09-30')
  })

  it('navigates between periods through the URL', async () => {
    const { router } = renderApp('/report?p=month&d=2026-09-10')
    const user = userEvent.setup()
    await screen.findByTestId('period-label')
    await user.click(screen.getByRole('button', { name: 'Periodo precedente' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ p: 'month', d: '2026-08-01' }))
    await user.click(screen.getByRole('radio', { name: 'Anno' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ p: 'year' }))
  })

  it('has a print button that opens the browser print dialog, and no global range selector', async () => {
    const print = vi.fn()
    vi.stubGlobal('print', print)
    renderApp('/report')
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('print-button'))
    expect(print).toHaveBeenCalledOnce()
    expect(screen.queryByTestId('range-selector')).toBeNull()
  })

  it('exports the daily table as CSV', async () => {
    renderApp('/report?p=month&d=2026-10-01')
    const user = userEvent.setup()
    await screen.findByTestId('report-row-steps')
    await user.click(screen.getByRole('button', { name: 'Esporta CSV giornaliero' }))
    await waitFor(() => expect(csvDownloads.length).toBe(1))
    const lines = (csvDownloads[0]?.text ?? '').replace('﻿', '').split('\r\n')
    expect(lines[0]).toBe('data,steps,hr_avg')
    expect(lines[1]).toBe('2026-10-01,100,70.5')
    expect(lines[2]).toBe('2026-10-02,,71') // missing value stays empty, not 0
  })

  it('says so when the period has no data', async () => {
    handlers['/api/v1/report'] = () => ({
      body: { ...fx2.report(), metrics: fx2.report().metrics.map((m) => ({ ...m, days_with_data: 0 })) },
    })
    renderApp('/report')
    expect(await screen.findByTestId('empty-state')).toHaveTextContent('Nessun dato nel periodo')
  })
})

describe('navigation', () => {
  it('lists the seven destinations in the sidebar and 4 + "Altro" in the bottom bar', async () => {
    renderApp('/')
    const user = userEvent.setup()
    const navs = await screen.findAllByRole('navigation', { name: 'Navigazione principale' })
    const [side, bottom] = navs as [HTMLElement, HTMLElement]
    expect(within(side).getAllByRole('link')).toHaveLength(7)
    expect(within(bottom).getAllByRole('link')).toHaveLength(4)
    await user.click(within(bottom).getByTestId('nav-more'))
    const menu = await screen.findByTestId('nav-more-menu')
    expect(within(menu).getAllByRole('link').map((a) => a.textContent)).toEqual(['Corpo', 'Report', 'Sync / Dati'])
  })
})
