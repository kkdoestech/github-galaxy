import { expect, test } from '@playwright/test'

// Runs against the static demo build: sample galaxies only, no backend needed.

test('opens a sample galaxy and lets you explore it', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('./')

  // the demo opens its first sample on its own
  const rows = page.locator('.cluster-row')
  await expect(rows.first()).toBeVisible()
  await expect(page.locator('.status')).toContainText('people')
  await expect(page.locator('canvas.galaxy-canvas')).toBeVisible()
  expect(page.url()).toContain('u=')

  // isolate a cluster
  await rows.nth(1).click()
  await expect(rows.nth(1)).toHaveAttribute('aria-pressed', 'true')

  // pick a person from the list: the details box fills in
  const member = page.locator('.cluster-members .link').first()
  const login = (await member.textContent())!.trim()
  await member.click()
  await expect(page.locator('.user-top')).toContainText(login)

  // find someone by name
  await page.fill('#find', login.toUpperCase())
  await page.getByRole('button', { name: 'Find' }).click()
  await expect(page.locator('.user-top')).toContainText(login)

  // Esc clears the selection
  await page.locator('canvas.galaxy-canvas').click({ position: { x: 5, y: 5 } })
  await page.keyboard.press('Escape')
  await expect(page.locator('.user-top')).toHaveCount(0)

  // the eigenvalue chart is drawn
  await expect(page.locator('svg.chart path').first()).toBeVisible()
  expect(errors).toEqual([])
})

test('a share link opens the same sample', async ({ page }) => {
  await page.goto('./?u=mitsuhiko')
  await expect(page.locator('.status')).toContainText('mitsuhiko')
  await expect(page.locator('.cluster-row').first()).toBeVisible()
})

test('works at phone width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('./')
  await expect(page.locator('.cluster-row').first()).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  expect(overflow).toBe(false)
})
