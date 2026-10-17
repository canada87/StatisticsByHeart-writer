import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fmtBytes } from '../lib/format'
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
    option?: { series?: { name: string; lineStyle?: { type?: string }; markArea?: { data: unknown[] }; markLine?: { data: { yAxis: number }[]; label?: { formatter?: string } } }[] }
  }) => (
    <div
      data-testid="echart-stub"
      data-active={activeIndex ?? ''}
      data-series={(option?.series ?? []).map((s) => `${s.name}:${s.lineStyle?.type ?? ''}`).join('|')}
      data-bands={option?.series?.find((s) => s.markArea)?.markArea?.data.length ?? 0}
      data-goal={option?.series?.find((s) => s.markLine)?.markLine?.data[0]?.yAxis ?? ''}
      data-goal-label={option?.series?.find((s) => s.markLine)?.markLine?.label?.formatter ?? ''}
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
    '/api/v1/storage': () => ({ body: fx2.storage }),
    '/api/v1/heart/points/week': () => ({ body: fx2.pointsWeek() }),
    '/api/v1/heart/points/rules': () => ({ body: fx2.pointsRules }),
    '/api/v1/heart/points': (url) =>
      url.searchParams.get('bucket') === 'day'
        ? { body: fx2.pointsSeriesDaily() }
        : { body: fx2.pointsSeries({ bucket: (url.searchParams.get('bucket') as 'week') ?? 'week' }) },
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

describe('Heart Points', () => {
  it('Overview card: ring toward 150 with the value, what is missing and the days left, as text', async () => {
    renderApp('/')
    const card = await screen.findByTestId('panel-heartpoints')
    expect(await within(card).findByTestId('points-value')).toHaveTextContent('96')
    expect(within(card).getByTestId('points-goal')).toHaveTextContent('150')
    expect(within(card).getByTestId('points-remaining')).toHaveTextContent('Mancano 54 punti, in 3 giorni')
    expect(within(card).getByRole('img', { name: '96 punti cardio su 150 della settimana' })).toBeInTheDocument()
    expect(within(card).getByTestId('points-week')).toHaveTextContent('Settimana in corso')
    expect(within(card).queryByTestId('points-hr-warning')).toBeNull()
  })

  it('asks for the week that contains the END of the selected window', async () => {
    renderApp('/?r=7d&end=2026-09-30')
    await screen.findByTestId('panel-heartpoints')
    await waitFor(() =>
      expect(urls.some((u) => u.pathname === '/api/v1/heart/points/week' && u.searchParams.get('date') === '2026-09-30')).toBe(true),
    )
  })

  it('says so when the goal is reached', async () => {
    handlers['/api/v1/heart/points/week'] = () => ({ body: fx2.pointsWeek({ total: 163, remaining: 0, reached: true }) })
    renderApp('/')
    expect(await screen.findByTestId('points-remaining')).toHaveTextContent('Obiettivo raggiunto')
  })

  it('warns, with the variable name, when HRmax is not configured', async () => {
    handlers['/api/v1/heart/points/week'] = () => ({ body: fx2.pointsWeek({ hr_configured: false }) })
    renderApp('/')
    const warn = await screen.findByTestId('points-hr-warning')
    expect(warn).toHaveTextContent('SBH_BIRTH_YEAR')
    expect(warn).toHaveTextContent('solo quelli dalla cadenza')
  })

  it('Cuore: bar chart with weekly granularity and the goal line, table and CSV', async () => {
    renderApp('/heart?r=90d')
    const user = userEvent.setup()
    const chart = await screen.findByTestId('chart-heartpoints')
    await waitFor(() =>
      expect(urls.some((u) => u.pathname === '/api/v1/heart/points' && u.searchParams.get('bucket') === 'week')).toBe(true),
    )
    const select = await within(chart).findByLabelText('Granularità')
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Giorno', 'Settimana', 'Mese', 'Anno'])
    expect(select).toHaveValue('week') // 90 days: the weekly view stays the default
    expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-goal', '150')
    expect(within(chart).getByTestId('chart-summary')).toHaveTextContent('2 settimane su 3 sopra l’obiettivo di 150')
    expect(within(chart).getByTestId('chart-summary')).toHaveTextContent('Periodo precedente: 400 punti')
    await user.click(within(chart).getByRole('button', { name: 'Mostra tabella' }))
    const table = within(chart).getByRole('table')
    const body = within(table).getAllByRole('row').map((r) => r.textContent)
    expect(body[1]).toContain('210')
    expect(body[1]).toContain('sì')
    expect(body[2]).toContain('no')
    expect(body[4]).toContain('in corso')
    await user.click(within(chart).getByRole('button', { name: 'Mostra grafico' }))
    await user.click(within(chart).getByRole('button', { name: 'Esporta CSV' }))
    await waitFor(() => expect(csvDownloads.length).toBe(1))
    expect(csvDownloads[0]?.text.split('\r\n')[0]).toContain('Obiettivo raggiunto')
  })

  it('7 and 30 day windows default to the daily view, with the 150/7 reference line, labelled', async () => {
    renderApp('/heart?r=30d')
    const chart = await screen.findByTestId('chart-heartpoints')
    await waitFor(() =>
      expect(urls.some((u) => u.pathname === '/api/v1/heart/points' && u.searchParams.get('bucket') === 'day')).toBe(true),
    )
    expect(await within(chart).findByLabelText('Granularità')).toHaveValue('day')
    await waitFor(() => expect(Number(within(chart).getByTestId('echart-stub').getAttribute('data-goal'))).toBeCloseTo(150 / 7, 5))
    const summary = within(chart).getByTestId('chart-summary')
    expect(summary).toHaveTextContent('5 giorni su 9 sopra ~21 (riferimento indicativo, non un obiettivo)')
    expect(summary).not.toHaveTextContent('obiettivo di 150')
    expect(summary).not.toHaveTextContent('raggiunto')
    expect(summary).toHaveTextContent('Oggi (parziale) non è conteggiato')
    expect(within(chart).getByTestId('points-chart-note')).toHaveTextContent('solo un riferimento indicativo')
    const user = userEvent.setup()
    await user.click(within(chart).getByRole('button', { name: 'Mostra tabella' }))
    expect(within(chart).getByRole('columnheader', { name: 'Sopra ~21' })).toBeInTheDocument()
  })

  it('the reference line label is generated from the backend values', async () => {
    handlers['/api/v1/heart/points'] = () => ({
      body: fx2.pointsSeriesDaily({ weekly_goal: 210, daily_reference: 30 }),
    })
    renderApp('/heart?r=7d')
    const chart = await screen.findByTestId('chart-heartpoints')
    await waitFor(() => expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-goal', '30'))
    expect(within(chart).getByTestId('echart-stub').getAttribute('data-goal-label')).toBe('Riferimento ~30/giorno (210/7)')
  })

  it('says so when the daily view was widened to weeks', async () => {
    handlers['/api/v1/heart/points'] = () => ({ body: fx2.pointsSeries({ coarsened: true }) })
    renderApp('/heart?r=30d')
    const chart = await screen.findByTestId('chart-heartpoints')
    await waitFor(() => expect(within(chart).getByTestId('chart-summary')).toHaveTextContent('Troppi giorni per il grafico: i dati sono aggregati per settimana'))
    // the chart follows the bucket the server used: the weekly goal line, not the daily reference
    expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-goal', '150')
  })

  it('the day choice survives changing nothing else; the user can still pick another one', async () => {
    renderApp('/heart?r=30d')
    const user = userEvent.setup()
    const chart = await screen.findByTestId('chart-heartpoints')
    await user.selectOptions(await within(chart).findByLabelText('Granularità'), 'week')
    expect(within(chart).getByLabelText('Granularità')).toHaveValue('week')
    await waitFor(() =>
      expect(urls.some((u) => u.pathname === '/api/v1/heart/points' && u.searchParams.get('bucket') === 'week')).toBe(true),
    )
  })

  it('month view has no goal line', async () => {
    renderApp('/heart')
    const user = userEvent.setup()
    const chart = await screen.findByTestId('chart-heartpoints')
    await user.selectOptions(await within(chart).findByLabelText('Granularità'), 'month')
    await waitFor(() => expect(urls.some((u) => u.searchParams.get('bucket') === 'month')).toBe(true))
    await waitFor(() => expect(within(chart).getByTestId('echart-stub')).toHaveAttribute('data-goal', ''))
  })

  it('Cuore: the rules panel lists the numbers the backend sends and says MET is not used', async () => {
    renderApp('/heart')
    const panel = await screen.findByTestId('points-rules')
    const list = await within(panel).findByTestId('points-rules-list')
    expect(list).toHaveTextContent('da 50% della FCmax → 1 punto, da 70% → 2 punti')
    expect(list).toHaveTextContent('da 100 passi al minuto → 1 punto, da 130 → 2 punti')
    expect(list).toHaveTextContent('non 3')
    expect(list).toHaveTextContent('FCmax usata oggi: 184 bpm (220 − età')
    expect(list).toHaveTextContent('da 92 bpm 1 punto, da 129 bpm 2 punti')
    expect(list).toHaveTextContent('al massimo 5 minuti prima')
    expect(list).toHaveTextContent('MET di Google Fit non si usa')
    expect(list).toHaveTextContent('nessuna esclusione degli allenamenti')
    expect(list).toHaveTextContent('Obiettivo settimanale: 150 punti')
    expect(list).toHaveTextContent('più lunghi di 60 minuti')
    expect(list).toHaveTextContent('150/7 ≈ 21 punti al giorno')
    expect(list).toHaveTextContent('non un obiettivo giornaliero')
  })

  it('the rules follow the backend values and the HRmax warning replaces the number', async () => {
    handlers['/api/v1/heart/points/rules'] = () => ({
      body: {
        ...fx2.pointsRules,
        weekly_goal: 200,
        cadence: { moderate_steps: 90, vigorous_steps: 120, max_record_minutes: 45 },
        heart_rate: { ...fx2.pointsRules.heart_rate, configured: false, hr_max: null, hr_max_source: null },
      },
    })
    renderApp('/heart')
    const list = await screen.findByTestId('points-rules-list')
    expect(list).toHaveTextContent('da 90 passi al minuto')
    expect(list).toHaveTextContent('Obiettivo settimanale: 200 punti')
    expect(within(list).getByText(/SBH_BIRTH_YEAR/)).toBeInTheDocument()
  })

  it('the HRmax override is described as such', async () => {
    handlers['/api/v1/heart/points/rules'] = () => ({
      body: { ...fx2.pointsRules, heart_rate: { ...fx2.pointsRules.heart_rate, hr_max: 195, hr_max_source: 'override' } },
    })
    renderApp('/heart')
    expect(await screen.findByTestId('points-rules-list')).toHaveTextContent('impostata in SBH_HR_MAX')
  })

  it('shows an empty state when there are no points', async () => {
    handlers['/api/v1/heart/points'] = () => ({
      body: fx2.pointsSeries({ points: [], summary: { total: 0, days: 0, buckets_complete: 0, weeks_over_goal: 0, days_over_reference: null } }),
    })
    renderApp('/heart')
    expect(await screen.findByText('Nessun punto cardio nell’intervallo')).toBeInTheDocument()
  })
})

describe('space and limits (Sync / Dati)', () => {
  it('shows the KPIs: database size, free disk as bar AND words, yearly growth as an estimate', async () => {
    renderApp('/sync?tab=storage')
    const db = await screen.findByTestId('kpi-storage-db')
    expect(within(db).getByTestId('kpi-value')).toHaveTextContent('50 MB')
    expect(db).toHaveTextContent('PostgreSQL 16.4')
    const disk = screen.getByTestId('kpi-storage-disk')
    expect(disk).toHaveTextContent('Disco della VM (stima)')
    expect(within(disk).getByTestId('kpi-value')).toHaveTextContent('70 GB')
    const meter = within(disk).getByRole('meter', { name: 'Spazio del disco usato' })
    expect(meter).toHaveAttribute('aria-valuenow', '70')
    expect(meter).toHaveAttribute('aria-valuetext', '70% libero')
    expect(within(disk).getByTestId('disk-gauge')).toHaveTextContent('70% libero') // words, not only colour
    expect(disk).toHaveTextContent('disco di Docker sulla VM')
    const growth = screen.getByTestId('kpi-storage-growth')
    expect(within(growth).getByTestId('kpi-value')).toHaveTextContent('≈ 36,5 MB')
    expect(growth).toHaveTextContent('Stima: 3 MB/mese di dati negli ultimi 30 giorni (3000 record, 40.000 campioni), proiettata a un anno')
    expect(growth).not.toHaveTextContent('backfill')
  })

  it('says so when the history is shorter than 30 days', async () => {
    handlers['/api/v1/storage'] = () => ({
      body: { ...fx2.storage, growth: { ...fx2.storage.growth, window_days: 9, partial_history: true } },
    })
    renderApp('/sync?tab=storage')
    expect(await screen.findByTestId('kpi-storage-growth')).toHaveTextContent('calcolata sui soli 9 giorni di storico')
  })

  it('lists every table with readable units, marking the estimated row counts', async () => {
    renderApp('/sync?tab=storage')
    const rows = await screen.findAllByTestId('storage-row')
    expect(rows.map((r) => r.getAttribute('data-table'))).toEqual(['health_sample', 'health_record', 'daily_metric', 'admin_user'])
    expect(rows[0]).toHaveTextContent('28,6 MB')
    expect(rows[0]).toHaveTextContent('≈ 400.000')
    expect(rows[0]).toHaveTextContent('stima') // for screen readers too
    expect(rows[1]).toHaveTextContent('30.000')
    expect(rows[1]).not.toHaveTextContent('≈')
    expect(rows[3]).toHaveTextContent('16 kB')
  })

  it('sorts by clicking the headers and tells assistive tech with aria-sort', async () => {
    renderApp('/sync?tab=storage')
    const user = userEvent.setup()
    const table = await screen.findByTestId('storage-table')
    const header = (name: RegExp) => within(table).getByRole('columnheader', { name })
    expect(header(/Totale/)).toHaveAttribute('aria-sort', 'descending')
    expect(header(/Tabella/)).toHaveAttribute('aria-sort', 'none')
    const order = () => screen.getAllByTestId('storage-row').map((r) => r.getAttribute('data-table'))

    await user.click(screen.getByTestId('sort-name'))
    expect(header(/Tabella/)).toHaveAttribute('aria-sort', 'ascending')
    expect(header(/Totale/)).toHaveAttribute('aria-sort', 'none')
    expect(order()).toEqual(['admin_user', 'daily_metric', 'health_record', 'health_sample'])
    await user.click(screen.getByTestId('sort-name'))
    expect(header(/Tabella/)).toHaveAttribute('aria-sort', 'descending')
    expect(order()).toEqual(['health_sample', 'health_record', 'daily_metric', 'admin_user'])

    await user.click(screen.getByTestId('sort-rows'))
    expect(header(/Righe/)).toHaveAttribute('aria-sort', 'descending')
    expect(order()).toEqual(['health_sample', 'health_record', 'daily_metric', 'admin_user'])
    await user.click(screen.getByTestId('sort-rows'))
    expect(order()).toEqual(['admin_user', 'daily_metric', 'health_record', 'health_sample'])
    await user.click(screen.getByTestId('sort-index_bytes'))
    expect(order()[0]).toBe('health_sample')
  })

  it('"Limiti e retention": one sentence per item, with the values the backend sent', async () => {
    renderApp('/sync?tab=storage')
    const list = await screen.findByTestId('limits-list')
    const items = within(list).getAllByRole('listitem')
    expect(items.map((i) => i.getAttribute('data-limit'))).toEqual([
      'retention',
      'soft_delete',
      'session_purge',
      'daily_recompute',
      'ingest_batch',
      'ingest_body',
      'route_points',
      'query_days',
      'intraday',
      'chart_points',
    ])
    expect(items[0]).toHaveTextContent('nessuna')
    expect(items[1]).toHaveTextContent('soft delete')
    expect(items[2]).toHaveTextContent('minuto 17')
    expect(items[2]).toHaveTextContent('7 giorni')
    expect(items[3]).toHaveTextContent('03:30')
    expect(items[4]).toHaveTextContent('500 record')
    expect(items[5]).toHaveTextContent('32 MB')
    expect(items[6]).toHaveTextContent('50.000 punti')
    expect(items[7]).toHaveTextContent('3660 giorni')
    expect(items[8]).toHaveTextContent('15 minuti fino a 3 giorni')
    expect(items[8]).toHaveTextContent('orarie fino a 31 giorni')
    expect(items[9]).toHaveTextContent('1000 punti')
  })

  it('does not hardcode the numbers: it follows what the API sends', async () => {
    handlers['/api/v1/storage'] = () => ({
      body: {
        ...fx2.storage,
        limits: { items: [{ id: 'ingest_batch', params: { max_records: 250 } }, { id: 'route_points', params: { max_points: 777 } }] },
      },
    })
    renderApp('/sync?tab=storage')
    const list = await screen.findByTestId('limits-list')
    expect(list).toHaveTextContent('250 record')
    expect(list).toHaveTextContent('777 punti')
    expect(list).not.toHaveTextContent('500 record')
  })

  it('shows soft-deleted records, first and last data', async () => {
    renderApp('/sync?tab=storage')
    const facts = await screen.findByTestId('storage-facts')
    expect(within(facts).getByTestId('deleted-count')).toHaveTextContent('10')
    expect(facts).toHaveTextContent('29.990')
    expect(facts).toHaveTextContent('01/01')
  })

  it('has no cleanup action: it is read-only', async () => {
    renderApp('/sync?tab=storage')
    await screen.findByTestId('storage-tab')
    const tab = screen.getByTestId('storage-tab')
    expect(within(tab).queryByRole('button', { name: /elimina|pulisci|purge|cancella/i })).toBeNull()
    expect(fetch).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ method: 'DELETE' }))
  })

  it('shows an error state, with retry, when the numbers cannot be read', async () => {
    handlers['/api/v1/storage'] = () => ({ status: 500, body: { error: { code: 'x', message: 'boom' } } })
    renderApp('/sync?tab=storage')
    expect(await screen.findByRole('button', { name: 'Riprova' })).toBeInTheDocument()
  })

  it('shows a loading state while waiting', async () => {
    handlers['/api/v1/storage'] = () => ({ body: fx2.storage })
    renderApp('/sync?tab=storage')
    expect(await screen.findByTestId('storage-tab')).toBeInTheDocument()
    await screen.findByTestId('kpi-storage-db')
  })

  it('an empty database: no growth yet and no data dates', async () => {
    handlers['/api/v1/storage'] = () => ({
      body: {
        ...fx2.storage,
        tables: [],
        records_live: 0,
        records_deleted: 0,
        first_data: null,
        last_data: null,
        last_ingest: null,
        growth: { window_days: 0, records: 0, samples: 0, bytes: 0, bytes_per_month: 0, bytes_per_year: 0, partial_history: false, estimated: true },
      },
    })
    renderApp('/sync?tab=storage')
    const growth = await screen.findByTestId('kpi-storage-growth')
    expect(within(growth).getByTestId('kpi-value')).toHaveTextContent('—')
    expect(growth).toHaveTextContent('Ancora nessun giorno completo')
    expect(within(screen.getByTestId('storage-facts')).getAllByText('—').length).toBeGreaterThanOrEqual(3)
  })
})

describe('byte formatting', () => {
  it('uses binary units with it-IT numbers', () => {
    expect(fmtBytes(0)).toBe('0 B')
    expect(fmtBytes(1536)).toBe('1,5 kB')
    expect(fmtBytes(52_428_800)).toBe('50 MB')
    expect(fmtBytes(1_073_741_824)).toBe('1 GB')
    expect(fmtBytes(null)).toBe('—')
  })
})

describe('extended report', () => {
  it('adds day / night heart rate and Heart Points rows, keeping all the other statistics', async () => {
    renderApp('/report?p=month&d=2026-09-10')
    await screen.findByTestId('report-row-steps')
    for (const key of ['steps', 'distance', 'active_kcal', 'total_kcal', 'heart_rate', 'resting_hr', 'hrv', 'spo2', 'sleep', 'workouts', 'weight', 'blood_pressure']) {
      expect(screen.getByTestId(`report-row-${key}`)).toBeInTheDocument()
    }
    const day = screen.getByTestId('report-row-hr_day')
    expect(day).toHaveTextContent('FC diurna')
    expect(day).toHaveTextContent('76 bpm')
    expect(within(day).getByTestId('delta')).toBeInTheDocument() // with the previous period
    const night = screen.getByTestId('report-row-hr_night')
    expect(night).toHaveTextContent('54 bpm')
    expect(within(night).getByTestId('delta')).toHaveAttribute('data-direction', 'down')
    const points = screen.getByTestId('report-row-heart_points')
    expect(points).toHaveTextContent('140 punti')
    const rows = screen.getAllByTestId(/^report-row-/).map((r) => r.getAttribute('data-testid'))
    expect(rows.indexOf('report-row-hr_day')).toBe(rows.indexOf('report-row-heart_rate') + 1)
  })

  it('Heart Points block: total, weekly mean, weeks above the goal, previous period', async () => {
    renderApp('/report?p=month&d=2026-09-10')
    const block = await screen.findByTestId('report-points')
    expect(within(block).getByTestId('report-points-total')).toHaveTextContent('140 punti')
    expect(within(block).getByTestId('report-points-weekly')).toHaveTextContent('140 punti')
    expect(within(block).getByTestId('report-points-goal')).toHaveTextContent('0 settimane su 1 sopra l’obiettivo')
    expect(block).toHaveTextContent('126 punti')
    expect(within(block).queryByTestId('points-hr-warning')).toBeNull()
  })

  it('workouts: only real ones, per type with number and time, and a pointer to the rules', async () => {
    renderApp('/report?p=month&d=2026-09-10')
    const types = await screen.findByTestId('report-workout-types')
    const rows = within(types).getAllByTestId('workout-type-row')
    expect(rows[0]).toHaveTextContent('Corsa')
    expect(rows[0]).toHaveTextContent('2')
    expect(rows[0]).toHaveTextContent('1 h 15 min')
    expect(rows[1]).toHaveTextContent('Ciclismo')
    expect(within(types).getByRole('columnheader', { name: 'Allenamenti veri' })).toBeInTheDocument()
    const note = screen.getByTestId('report-workouts-rules')
    expect(note).toHaveTextContent('Contano solo gli allenamenti veri')
    expect(within(note).getByRole('link', { name: 'Vedi le regole' })).toHaveAttribute('href', expect.stringContaining('/activity'))
  })

  it('month by month: a row per month with the partial ones flagged, daily means and totals', async () => {
    handlers['/api/v1/report'] = () => ({ body: { ...fx2.report(), monthly: fx2.monthlyFixture('2026-07-20', '2026-10-15') } })
    renderApp('/report?p=custom&from=2026-07-20&to=2026-10-15')
    const monthly = await screen.findByTestId('report-monthly')
    const avg = within(monthly).getByTestId('monthly-avg')
    const rows = within(avg).getAllByTestId('month-row')
    expect(rows).toHaveLength(4) // jul, aug, sep, oct
    expect(rows.map((r) => r.getAttribute('data-partial'))).toEqual(['true', 'false', 'false', 'true'])
    expect(within(rows[0] as HTMLElement).getByTestId('month-partial')).toHaveTextContent('parziale, 12 gg')
    expect(within(rows[1] as HTMLElement).queryByTestId('month-partial')).toBeNull()
    expect(rows[1]).toHaveTextContent('ago 2026')
    // headers with scope, caption, and the day / night columns next to the heart rate
    expect(within(avg).getAllByRole('columnheader').map((h) => h.textContent)).toEqual(
      expect.arrayContaining(['Mese', expect.stringContaining('FC diurna'), expect.stringContaining('FC notturna')]),
    )
    expect(within(avg).getAllByRole('rowheader')).toHaveLength(4)
    expect(rows[1]).toHaveTextContent('77') // hr_day of the 2nd month: 76 + 1
    const sum = within(monthly).getByTestId('monthly-sum')
    expect(within(sum).getAllByTestId('month-row')[1]).toHaveTextContent('340') // heart points of the 2nd month: 300 + 40
    expect(within(monthly).getByText(/Parziale = il periodo non copre tutto il mese/)).toBeInTheDocument()
  })

  it('one whole week inside one month does not repeat the summary in a month table', async () => {
    renderApp('/report')
    await screen.findByTestId('report-row-steps')
    expect(screen.queryByTestId('report-monthly')).toBeNull()
  })

  it('a single whole month still shows its one row, not partial', async () => {
    handlers['/api/v1/report'] = () => ({ body: { ...fx2.report(), monthly: fx2.monthlyFixture('2026-09-01', '2026-09-30') } })
    renderApp('/report?p=month&d=2026-09-10')
    const monthly = await screen.findByTestId('report-monthly')
    const rows = within(monthly).getAllByTestId('month-row')
    expect(rows.length).toBe(2) // avg table and totals table, one row each
    expect(rows.every((r) => r.getAttribute('data-partial') === 'false')).toBe(true)
  })

  it('big charts: one per metric with data, monthly granularity when the period spans months', async () => {
    handlers['/api/v1/report'] = () => ({ body: { ...fx2.report(), monthly: fx2.monthlyFixture('2026-07-20', '2026-10-15') } })
    renderApp('/report?p=custom&from=2026-07-20&to=2026-10-15')
    const charts = await screen.findByTestId('report-charts')
    await waitFor(() => expect(within(charts).getAllByTestId('echart-stub').length).toBeGreaterThanOrEqual(8))
    expect(within(charts).getByText(/i grafici sono per mese/)).toBeInTheDocument()
    await waitFor(() =>
      expect(urls.some((u) => u.pathname === '/api/v1/metrics/Steps/series' && u.searchParams.get('bucket') === 'month')).toBe(true),
    )
    expect(charts.querySelectorAll('.report-chart').length).toBeGreaterThanOrEqual(8)
    // the heart-rate chart is the day / night one, and Heart Points are there too
    expect(within(charts).getByTestId('trend-heartRate')).toBeInTheDocument()
    expect(within(charts).getByTestId('chart-heartpoints')).toBeInTheDocument()
  })

  it('a period within a month keeps the daily default for the big charts', async () => {
    renderApp('/report?p=month&d=2026-09-10')
    await screen.findByTestId('report-charts')
    await waitFor(() =>
      expect(urls.some((u) => u.pathname === '/api/v1/metrics/Steps/series' && u.searchParams.get('bucket') === 'day')).toBe(true),
    )
  })

  it('charts of metrics without data are not drawn', async () => {
    handlers['/api/v1/report'] = () => ({ body: fx2.report({ noBloodPressure: true }) })
    renderApp('/report?p=month&d=2026-09-10')
    await screen.findByTestId('report-charts')
    expect(screen.queryByTestId('trend-systolic')).toBeNull()
  })

  it('exports the monthly table as CSV, and the daily CSV keeps coming from the daily endpoint', async () => {
    handlers['/api/v1/report'] = () => ({ body: { ...fx2.report(), monthly: fx2.monthlyFixture('2026-07-20', '2026-10-15') } })
    renderApp('/report?p=custom&from=2026-07-20&to=2026-10-15')
    const user = userEvent.setup()
    await user.click(await screen.findByTestId('export-monthly'))
    await waitFor(() => expect(csvDownloads.length).toBe(1))
    const lines = (csvDownloads[0]?.text ?? '').split('\r\n')
    expect(lines[0]).toContain('mese')
    expect(lines[0]).toContain('hr_day')
    expect(lines[0]).toContain('heart_points')
    expect(lines[1]).toContain('2026-07')
    expect(lines[1]).toContain('si') // the first month is partial
    expect(lines.filter(Boolean).length).toBe(5) // header + 4 months
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
    expect(screen.getByTestId('report-workouts')).toHaveTextContent('Corsa 2')
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
