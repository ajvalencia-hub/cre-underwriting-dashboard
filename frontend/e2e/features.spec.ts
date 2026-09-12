import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// Wave 2 surfaces against the REAL backend: Settings (theme), Portfolio,
// Risk (run button + inline seed validation), the Compare tab and a tag
// round-trip on the pipeline. Every test creates its own deals through the
// API and deletes them afterwards — the smoke asserts on the exact deal
// list, and every spec shares the one scratch database (workers=1).

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ANALYTIC_INPUTS = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '../../backend/tests/fixtures/analytic_acquisition.json'),
    'utf-8',
  ),
) as Record<string, unknown>

const created: string[] = []

async function createDeal(
  request: APIRequestContext,
  name: string,
  overrides: Record<string, unknown> = {},
): Promise<string> {
  const res = await request.post('/api/deals', {
    data: { name, inputs: { ...ANALYTIC_INPUTS, ...overrides } },
  })
  expect(res.ok()).toBeTruthy()
  const id = (await res.json()).id as string
  created.push(id)
  return id
}

async function openDeal(page: Page, name: string) {
  await page.goto('/')
  const dealSelect = page.locator('select').first()
  await expect(dealSelect).toBeVisible()
  await dealSelect.selectOption({ label: name })
}

test.afterEach(async ({ request }) => {
  for (const id of created.splice(0)) await request.delete(`/api/deals/${id}`)
})

test('settings theme toggle, portfolio table, and risk seed validation', async ({ page, request }) => {
  await createDeal(request, 'Wave2 Alpha')
  await openDeal(page, 'Wave2 Alpha')

  // Settings: choosing Dark stamps `.dark` on <html>; Light removes it.
  await page.getByRole('tab', { name: '⚙ Settings' }).click()
  await page.getByRole('radio', { name: /^Dark/ }).check()
  await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  await page.getByRole('radio', { name: /^Light/ }).check()
  await expect(page.locator('html')).not.toHaveClass(/\bdark\b/)

  // Portfolio: the roll-up table renders with the acquisition row.
  await page.getByRole('tab', { name: 'Portfolio' }).click()
  await expect(page.getByText('TOTALS BY DEAL TYPE')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('td', { hasText: 'acquisition' }).first()).toBeVisible()

  // Risk: the Run button exists and a NaN seed is rejected inline.
  await page.getByRole('tab', { name: '5b. Risk' }).click()
  await expect(page.getByRole('button', { name: 'Run simulation' })).toBeVisible()
  const seed = page.getByLabel('Seed (blank = random)')
  await seed.fill('abc')
  await expect(page.getByText('Seed must be a non-negative whole number')).toBeVisible()
  await expect(seed).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByRole('button', { name: 'Run simulation' })).toBeDisabled()
})

test('compare tab lays two deals side by side with a CSV export', async ({ page, request }) => {
  await createDeal(request, 'Wave2 Base')
  await createDeal(request, 'Wave2 Tight Cap', { exitCapRatePct: 0.05 })
  await openDeal(page, 'Wave2 Base')

  await page.getByRole('tab', { name: 'Compare' }).click()
  await page.getByRole('checkbox', { name: /Wave2 Base/ }).check()
  await page.getByRole('checkbox', { name: /Wave2 Tight Cap/ }).check()

  const table = page.getByRole('table', { name: 'Deal comparison' })
  await expect(table.getByRole('columnheader', { name: /Wave2 Base/ })).toBeVisible()
  await expect(table.getByRole('columnheader', { name: /Wave2 Tight Cap/ })).toBeVisible()
  // Both columns compute through the native engine (no "not computable").
  await expect(page.getByText('computing…')).toHaveCount(0, { timeout: 20_000 })
  await expect(page.getByText('not computable')).toHaveCount(0)
  const irrRow = table.locator('tr', { hasText: 'Levered IRR' }).first()
  await expect(irrRow).toBeVisible()
  await expect(irrRow.locator('td').nth(1)).toHaveText(/%$/)
  await expect(irrRow.locator('td').nth(2)).toHaveText(/%$/)
  // Direction-aware highlight: exactly one best cell on that row.
  await expect(irrRow.locator('td.bg-emerald-50')).toHaveCount(1)

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV' }).click()
  expect((await downloadPromise).suggestedFilename()).toBe('deal-comparison.csv')

  // The selection survives a reload (safeStorage).
  await page.reload()
  await page.getByRole('tab', { name: 'Compare' }).click()
  await expect(page.getByRole('checkbox', { name: /Wave2 Base/ })).toBeChecked()
})

test('tag round-trip: header chip row, pipeline chips + filter, removal', async ({ page, request }) => {
  const taggedId = await createDeal(request, 'Wave2 Tagged')
  await createDeal(request, 'Wave2 Plain')
  await openDeal(page, 'Wave2 Tagged')

  // Add a tag from the header chip row (Enter commits).
  const tagInput = page.getByLabel('Add a tag (press Enter)')
  await tagInput.fill('Core Plus')
  await tagInput.press('Enter')
  const tagGroup = page.getByRole('group', { name: 'Deal tags' })
  await expect(tagGroup.getByText('core plus')).toBeVisible()
  await expect
    .poll(async () => ((await (await request.get(`/api/deals/${taggedId}`)).json()).tags as string[]))
    .toEqual(['core plus'])

  // Pipeline: the row shows the chip; the tag filter narrows the board.
  await page.getByRole('tab', { name: 'Deals' }).click()
  const taggedRow = page.locator('tr', { hasText: 'Wave2 Tagged' }).first()
  await expect(taggedRow.getByText('core plus')).toBeVisible()
  await expect(page.locator('tr', { hasText: 'Wave2 Plain' }).first()).toBeVisible()
  await page
    .getByRole('group', { name: 'Filter by Tags' })
    .getByRole('button', { name: 'core plus' })
    .click()
  await expect(page.locator('tr', { hasText: 'Wave2 Plain' })).toHaveCount(0)
  await expect(taggedRow).toBeVisible()

  // Remove it from the header; the chip and the server copy both clear.
  await page.getByRole('tab', { name: '3. Deal Inputs' }).click()
  await tagGroup.getByRole('button', { name: 'Remove tag core plus' }).click()
  await expect(tagGroup.getByText('core plus')).toHaveCount(0)
  await expect
    .poll(async () => ((await (await request.get(`/api/deals/${taggedId}`)).json()).tags as string[]))
    .toEqual([])
})
