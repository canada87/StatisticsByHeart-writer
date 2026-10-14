import AxeBuilder from '@axe-core/playwright'
import { type Page, expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
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

test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }))

async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Nome utente').fill(USER)
  await page.getByLabel('Password', { exact: true }).fill(PASSWORD)
  await page.getByRole('button', { name: 'Accedi' }).click()
  await expect(page.getByRole('heading', { level: 1, name: 'Panoramica' })).toBeVisible()
}

async function settled(page: Page) {
  // charts are canvas: wait for the lazy chunk + first paint, and for skeletons to go away
  await expect(page.getByRole('status', { name: 'Caricamento…' })).toHaveCount(0, { timeout: 15_000 })
  await page.waitForTimeout(600)
}

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
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

  test('navigation: sidebar from 1024px, bottom nav below', async ({ page }) => {
    await login(page)
    await page.setViewportSize({ width: 1024, height: 768 })
    await expect(page.locator('aside').getByRole('link', { name: 'Sync / Dati' })).toBeVisible()
    await expect(page.locator('nav.fixed.bottom-0')).toBeHidden()
    await page.setViewportSize({ width: 768, height: 1024 })
    await expect(page.locator('nav.fixed.bottom-0').getByRole('link', { name: 'Sync / Dati' })).toBeVisible()
    await expect(page.locator('aside')).toBeHidden()
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

  for (const vp of VIEWPORTS) {
    test(`screenshots + a11y + no horizontal scroll @${vp.name}`, async ({ page }) => {
      await page.emulateMedia({ reducedMotion: 'reduce' })
      await page.setViewportSize(vp)
      await login(page)
      await settled(page)
      await noHorizontalScroll(page)
      await a11y(page)
      await page.screenshot({ path: join(SHOTS, `overview-${vp.name}.png`), fullPage: true })

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
