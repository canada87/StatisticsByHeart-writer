import AxeBuilder from '@axe-core/playwright'
import { type Page, expect, test } from '@playwright/test'
import { mkdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

// Dev-stack credentials (docker/compose.dev.yml). Synthetic data only.
const USER = process.env.E2E_USER ?? 'admin'
const PASSWORD = process.env.E2E_PASSWORD ?? 'dev-password-change-me'
const SHOTS = join(import.meta.dirname, '..', '..', 'docs', 'screenshots')
const VIEWPORTS = [
  { name: '375', width: 375, height: 812 },
  { name: '768', width: 768, height: 1024 },
  { name: '1024', width: 1024, height: 768 },
  { name: '1440', width: 1440, height: 900 },
] as const

// Pages with their heading; trend pages use 30 days so the charts have enough points.
const PAGES = [
  { id: 'overview', path: '/', h1: 'Panoramica' },
  { id: 'heart', path: '/heart?r=30d', h1: 'Cuore' },
  { id: 'sleep', path: '/sleep?r=30d', h1: 'Sonno' },
  { id: 'activity', path: '/activity?r=30d', h1: 'Attività' },
  { id: 'body', path: '/body?r=90d', h1: 'Corpo' },
  { id: 'report', path: '/report?p=month', h1: 'Report' },
] as const

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }))

async function login(page: Page, expectHeading = 'Panoramica') {
  await page.goto('/login')
  await page.getByLabel('Nome utente').fill(USER)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Accedi' }).click()
  await expect(page.getByRole('heading', { level: 1, name: expectHeading })).toBeVisible()
}

async function settled(page: Page) {
  // charts are canvas: wait for the lazy chunk + first paint, and for skeletons to go away
  await expect(page.getByRole('status', { name: 'Caricamento…' })).toHaveCount(0, { timeout: 20_000 })
  await page.waitForTimeout(700)
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow, `horizontal overflow on ${page.url()}`).toBeLessThanOrEqual(0)
}

async function a11y(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze()
  const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
}

test.describe('login', () => {
  test('rejects wrong credentials with an accessible message', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Nome utente').fill(USER)
    await page.getByLabel('Password', { exact: true }).fill('wrong-wrong-wrong')
    await page.getByRole('button', { name: 'Accedi' }).click()
    await expect(page.getByRole('alert')).toContainText('non corretti')
  })

  test('unauthenticated deep links redirect to login and come back after', async ({ page }) => {
    await page.goto('/sync')
    await expect(page).toHaveURL(/\/login/)
    await page.getByLabel('Nome utente').fill(USER)
    await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
    await page.getByRole('button', { name: 'Accedi' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Sync / Dati' })).toBeVisible()
  })

  test('password can be pasted and revealed', async ({ page }) => {
    await page.goto('/login')
    const pass = page.getByLabel('Password', { exact: true })
    await pass.fill('incollata')
    await page.getByRole('button', { name: 'Mostra password' }).click()
    await expect(pass).toHaveAttribute('type', 'text')
  })

  for (const vp of VIEWPORTS) {
    test(`screenshot + a11y @${vp.name}`, async ({ page }) => {
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.setViewportSize(vp)
      await page.goto('/login')
      await expect(page.getByRole('button', { name: 'Accedi' })).toBeVisible()
      await noHorizontalScroll(page)
      await a11y(page)
      await page.screenshot({ path: join(SHOTS, `login-${vp.name}.png`) })
    })
  }
})

test.describe('dashboard (synthetic data)', () => {
  test('overview shows real numbers, range lives in the URL, logout works', async ({ page }) => {
    await login(page)
    await settled(page)
    await expect(page.getByTestId('steps-value')).not.toHaveText('—')
    await expect(page.getByTestId('panel-sleep')).toContainText('Notte del')
    await expect(page.getByTestId('activities').locator('li').first()).toBeVisible()

    await page.getByRole('radio', { name: '30g' }).click()
    await expect(page).toHaveURL(/r=30d/)
    await expect(page.getByTestId('chart-summary').first()).toContainText('giorno')
    await page.reload()
    await expect(page.getByRole('radio', { name: '30g' })).toHaveAttribute('aria-checked', 'true')

    await page.getByRole('button', { name: 'Mostra tabella' }).first().click()
    await expect(page.getByRole('table').first()).toBeVisible()

    await page.getByRole('button', { name: 'Esci' }).first().click()
    await expect(page).toHaveURL(/\/login/)
  })

  test('sidebar spans the whole page height and the bento grid has no hole', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await login(page)
    await settled(page)
    const { aside, doc } = await page.evaluate(() => ({
      aside: document.querySelector('aside')?.getBoundingClientRect().height ?? 0,
      doc: document.documentElement.scrollHeight,
    }))
    expect(doc).toBeGreaterThan(900) // the page scrolls...
    expect(aside).toBeGreaterThanOrEqual(doc - 1) // ...and the sidebar column covers all of it
    const sleep = await page.getByTestId('panel-sleep').boundingBox()
    const activities = await page.getByTestId('panel-activities').boundingBox()
    expect(sleep && activities).toBeTruthy()
    // second row ends flush with the first (no empty tile next to "Attività recenti")
    expect(Math.abs((activities?.x ?? 0) + (activities?.width ?? 0) - ((sleep?.x ?? 0) + (sleep?.width ?? 0)))).toBeLessThan(2)
  })

  test('sync / dati: runs, inventory per source, reconciliation flags double counting', async ({ page }) => {
    await login(page)
    await page.goto('/sync')
    await expect(page.getByTestId('sync-run').first()).toBeVisible()

    await page.getByRole('tab', { name: 'Inventario' }).click()
    await expect(page.getByTestId('source-card')).toHaveCount(3)
    await expect(page.getByTestId('type-row').first()).toBeVisible()

    await page.getByRole('tab', { name: 'Riconciliazione' }).click()
    await expect(page.getByTestId('recon-row').first()).toBeVisible()
    await expect(page.getByText('Sovrapposizione').first()).toBeVisible()
    await expect(page.getByTestId('recon-row').first()).toHaveAttribute('data-status', 'match')
    await expect(page).toHaveURL(/tab=recon/)
  })

  test('navigation: sidebar from 1024px with 7 entries; below, 4 + "Altro"', async ({ page }) => {
    await login(page)
    await page.setViewportSize({ width: 1024, height: 768 })
    const side = page.locator('aside nav')
    await expect(side.getByRole('link')).toHaveCount(7)
    await expect(page.locator('nav.fixed.bottom-0')).toBeHidden()

    await page.setViewportSize({ width: 768, height: 1024 })
    await expect(page.locator('aside')).toBeHidden()
    const bottom = page.locator('nav.fixed.bottom-0')
    await expect(bottom.getByRole('link')).toHaveCount(4) // Panoramica, Cuore, Sonno, Attività
    await bottom.getByTestId('nav-more').click()
    const menu = page.getByTestId('nav-more-menu')
    await expect(menu.getByRole('link')).toHaveCount(3) // Corpo, Report, Sync / Dati
    await menu.getByRole('link', { name: 'Report' }).click()
    await expect(page.getByRole('heading', { level: 1, name: 'Report' })).toBeVisible()
    await expect(page.getByTestId('nav-more')).toHaveClass(/text-accent-glow/) // "Altro" shows it is current
  })

  test('reduced motion: no running animations', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await login(page)
    await settled(page)
    const running = await page.evaluate(() =>
      document.getAnimations().filter((a) => a.playState === 'running' && a.effect?.getTiming().iterations === Infinity).length,
    )
    expect(running).toBe(0)
  })
})

test.describe('trends (synthetic data)', () => {
  test('heart page: KPIs with delta arrow + text, granularity, moving average, previous period', async ({ page }) => {
    await login(page)
    await page.goto('/heart?r=30d')
    await settled(page)
    const kpi = page.getByTestId('kpi-heartRate')
    await expect(kpi.getByTestId('kpi-value')).not.toHaveText('—')
    const delta = kpi.getByTestId('delta')
    await expect(delta).toContainText('vs periodo prec.')
    await expect(delta).toHaveAttribute('data-direction', /up|down|flat/)

    const chart = page.getByTestId('trend-heartRate')
    await expect(chart.getByTestId('granularity-actual')).toContainText('giorno')
    await chart.getByLabel('Granularità').selectOption('week')
    await expect(chart.getByTestId('granularity-actual')).toContainText('settimana')
    await chart.getByLabel('Granularità').selectOption('day')

    const ma = chart.getByRole('button', { name: /Media mobile 7g/ })
    await expect(ma).toHaveAttribute('aria-pressed', 'false')
    await ma.click()
    await expect(ma).toHaveAttribute('aria-pressed', 'true')
    const prev = chart.getByRole('button', { name: 'Periodo precedente' })
    await prev.click()
    await expect(prev).toHaveAttribute('aria-pressed', 'true')
    await expect(chart.getByTestId('chart-summary')).toContainText('Tendenza')
  })

  test('chart values are reachable by keyboard and exportable', async ({ page }) => {
    await login(page)
    await page.goto('/heart?r=30d')
    await settled(page)
    const chart = page.getByTestId('trend-restingHr')
    await expect(chart.getByRole('slider')).toHaveCount(0) // no range bar under the chart
    const focusable = chart.getByTestId('chart-focus')
    await focusable.focus()
    await expect(focusable).toBeFocused()
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('ArrowRight')
    await expect(chart.getByTestId('chart-readout')).toContainText('bpm')
    await page.keyboard.press('End')
    await expect(chart.getByTestId('chart-readout')).toContainText('bpm')
    await page.keyboard.press('Escape')
    await expect(chart.getByTestId('chart-readout')).toHaveText('')

    await chart.getByRole('button', { name: 'Mostra tabella' }).click()
    await expect(chart.getByRole('table')).toBeVisible()
    await chart.getByRole('button', { name: 'Mostra grafico' }).click()

    const [download] = await Promise.all([page.waitForEvent('download'), chart.getByRole('button', { name: 'Esporta CSV' }).click()])
    expect(download.suggestedFilename()).toMatch(/^restingHr_.*\.csv$/)
    const body = readFileSync(await download.path(), 'utf8')
    expect(body.split('\r\n')[0]).toContain('Data')
    expect(body.split('\r\n').length).toBeGreaterThan(20)
  })

  test('range arrows move the window, live in the URL and survive back/forward', async ({ page }) => {
    await login(page)
    await page.goto('/heart?r=7d')
    await settled(page)
    const prev = page.getByRole('button', { name: 'Intervallo precedente' })
    const next = page.getByRole('button', { name: 'Intervallo successivo' })
    await expect(next).toBeDisabled()
    const box = await prev.boundingBox()
    expect(box?.width).toBeGreaterThanOrEqual(44)
    expect(box?.height).toBeGreaterThanOrEqual(44)
    await prev.click()
    await expect(page).toHaveURL(/end=\d{4}-\d{2}-\d{2}/)
    await expect(page.getByTestId('range-window')).toBeVisible()
    await expect(next).toBeEnabled()
    await settled(page)
    await page.goBack()
    await expect(page).not.toHaveURL(/end=/)
    await expect(next).toBeDisabled()
    await page.goto('/heart?r=30d&end=2026-01-31') // deep link
    await expect(page.getByTestId('range-window')).toContainText('31/01/2026')
    await page.getByRole('radio', { name: 'Tutto' }).click()
    await expect(prev).toHaveCount(0)
  })

  test('hourly averages are offered up to 31 days', async ({ page }) => {
    await login(page)
    await page.goto('/heart?r=30d')
    await settled(page)
    const chart = page.getByTestId('trend-heartRate')
    await chart.getByLabel('Granularità').selectOption('hour')
    await expect(chart.getByTestId('chart-summary')).toContainText('ora')
    await page.goto('/heart?r=90d')
    await settled(page)
    await expect(page.getByTestId('trend-heartRate').getByLabel('Granularità').locator('option', { hasText: 'Ora' })).toHaveCount(0)
  })

  test('the "Tutto" range reaches the first day with data', async ({ page }) => {
    await login(page)
    await page.goto('/activity')
    await page.getByRole('radio', { name: 'Tutto' }).click()
    await expect(page).toHaveURL(/r=all/)
    await settled(page)
    // seed: 90 days of data -> the weekly/day chart covers all of it
    await expect(page.getByTestId('trend-steps').getByTestId('chart-summary')).toContainText(/\d+ valori/)
    const text = await page.getByTestId('trend-steps').getByTestId('chart-summary').innerText()
    const n = Number(/(\d+) valori/.exec(text)?.[1])
    expect(n).toBeGreaterThanOrEqual(80)
  })

  test('sleep page: schedule and stages charts, regularity KPI', async ({ page }) => {
    await login(page)
    await page.goto('/sleep?r=30d')
    await settled(page)
    await expect(page.getByTestId('kpi-sleep-regularity')).toContainText('±')
    await expect(page.getByTestId('chart-sleep-stages').getByTestId('chart-summary')).toContainText('profondo')
    await expect(page.getByTestId('chart-sleep-schedule').getByTestId('chart-summary')).toContainText('Addormentamento medio')
  })

  test('activity page lists workouts with kcal and heart rate and exports them', async ({ page }) => {
    await login(page)
    await page.goto('/activity?r=30d')
    await settled(page)
    const rows = page.getByTestId('workout-row')
    await expect(rows.first()).toBeVisible()
    await expect(rows.first()).toContainText('kcal')
    await expect(rows.first()).toContainText('bpm')
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId('panel-workouts').getByRole('button', { name: 'Esporta CSV' }).click()])
    expect(readFileSync(await download.path(), 'utf8')).toContain('durata_s')
  })

  test('body page: weight and blood pressure with indicative bands', async ({ page }) => {
    await login(page)
    await page.goto('/body?r=90d')
    await settled(page)
    await expect(page.getByTestId('trend-weight')).toBeVisible()
    const bp = page.getByTestId('trend-systolic')
    await expect(bp.getByTestId('reference-note')).toContainText('indicative')
    await expect(bp.getByTestId('chart-summary')).toContainText('Pressione diastolica')
  })
})

test.describe('report (synthetic data)', () => {
  test('period lives in the URL; summary has the 12 metrics; CSV export works', async ({ page }) => {
    await login(page)
    await page.goto('/report?p=month')
    await settled(page)
    await expect(page.getByTestId('period-label')).toContainText('2026')
    for (const key of ['steps', 'heart_rate', 'resting_hr', 'sleep', 'workouts', 'active_kcal', 'total_kcal', 'distance', 'weight', 'spo2', 'hrv', 'blood_pressure']) {
      await expect(page.getByTestId(`report-row-${key}`)).toBeVisible()
    }
    await page.getByRole('radio', { name: 'Settimana' }).click()
    await expect(page).not.toHaveURL(/p=month/)
    await page.getByRole('button', { name: 'Periodo precedente' }).click()
    await expect(page).toHaveURL(/d=\d{4}-\d{2}-\d{2}/)
    await page.reload()
    await expect(page).toHaveURL(/d=\d{4}-\d{2}-\d{2}/) // reopening the URL restores the same report

    await page.goto('/report?p=month')
    await settled(page)
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Esporta CSV giornaliero' }).click()])
    const csv = readFileSync(await download.path(), 'utf8').split('\r\n')
    expect(csv[0]).toMatch(/^﻿data,steps,distance_m,/)
    expect(csv.length).toBeGreaterThan(10)
  })

  test('print preview: light theme, no HUD chrome, report content intact', async ({ page }) => {
    await page.setViewportSize({ width: 794, height: 1123 }) // A4 at 96 dpi
    await login(page)
    await page.goto('/report?p=month')
    await settled(page)
    await page.emulateMedia({ media: 'print', reducedMotion: 'reduce' })
    await expect(page.locator('aside')).toBeHidden()
    await expect(page.locator('nav.fixed')).toBeHidden()
    await expect(page.getByTestId('print-button')).toBeHidden()
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor)
    expect(bg).toBe('rgb(255, 255, 255)')
    await expect(page.getByTestId('report-summary')).toBeVisible()
    await page.screenshot({ path: join(SHOTS, 'report-print.png'), fullPage: true })
    await page.pdf({ path: join(SHOTS, 'report-print.pdf'), format: 'A4', printBackground: false })
  })
})

test.describe('all pages: screenshots, a11y, no horizontal scroll', () => {
  for (const vp of VIEWPORTS) {
    test(`pages @${vp.name}`, async ({ page }) => {
      test.setTimeout(180_000)
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.setViewportSize(vp)
      await login(page)
      for (const p of PAGES) {
        await page.goto(p.path)
        await expect(page.getByRole('heading', { level: 1, name: p.h1 })).toBeVisible()
        await settled(page)
        await noHorizontalScroll(page)
        await a11y(page)
        await page.screenshot({ path: join(SHOTS, `${p.id}-${vp.name}.png`), fullPage: true })
      }
      for (const [tab, label] of [
        ['sync', 'Sync'],
        ['inventory', 'Inventario'],
        ['recon', 'Riconciliazione'],
      ] as const) {
        await page.goto(tab === 'sync' ? '/sync' : `/sync?tab=${tab}`)
        await expect(page.getByRole('tab', { name: label })).toHaveAttribute('data-state', 'active')
        await settled(page)
        await noHorizontalScroll(page)
        await a11y(page)
        await page.screenshot({ path: join(SHOTS, `sync-${tab}-${vp.name}.png`), fullPage: true })
      }
    })
  }
})
