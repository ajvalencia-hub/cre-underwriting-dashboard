import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// Run 6 surfaces against the REAL backend: Settings (theme, workflow,
// backup download), Portfolio, Risk (inline seed validation), Compare, tags
// (header ↔ pipeline) and the pipeline's sort / bulk tags / archive views.
// Every test creates its own deals through the API and deletes them
// afterwards — the smoke asserts on the exact deal list, and every spec
// shares the one scratch database (workers: 1).

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ANALYTIC_INPUTS = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '../../backend/tests/fixtures/analytic_acquisition.json'), 'utf-8'),
) as Record<string, unknown>
delete ANALYTIC_INPUTS._comment

const created: string[] = []

async function createDeal(
  request: APIRequestContext,
  name: string,
  overrides: Record<string, unknown> = {},
): Promise<string> {
  const res = await request.post('/api/deals', { data: { name, inputs: { ...ANALYTIC_INPUTS, ...overrides } } })
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

const rail = (page: Page, label: string) => page.getByRole('button', { name: label, exact: true })

test.afterEach(async ({ request }) => {
  for (const id of created.splice(0)) await request.delete(`/api/deals/${id}`)
})

test('settings theme + workflow + backup download, portfolio table, risk seed validation', async ({ page, request }) => {
  await createDeal(request, 'Run6 Alpha')
  await openDeal(page, 'Run6 Alpha')

  // Settings: choosing Dark stamps `.dark` on <html>; Light removes it.
  await rail(page, 'Settings').click()
  await page.getByRole('radio', { name: /^Dark/ }).check()
  await expect(page.locator('html')).toHaveClass(/\bdark\b/)
  await page.getByRole('radio', { name: /^Light/ }).check()
  await expect(page.locator('html')).not.toHaveClass(/\bdark\b/)

  // Workflow: the New Deal default is remembered across a reload.
  const workflow = page.getByRole('group', { name: 'Default type for New Deal' })
  await workflow.getByRole('radio', { name: /^Development/ }).check()
  await page.reload()
  await rail(page, 'Settings').click()
  await expect(workflow.getByRole('radio', { name: /^Development/ })).toBeChecked()
  await workflow.getByRole('radio', { name: /^Ask each time/ }).check()

  // Backups: a fresh snapshot offers a Download of its database file.
  await page.getByRole('button', { name: 'Back up now' }).click()
  await expect(page.getByText(/^Snapshot .* created\.$/)).toBeVisible({ timeout: 20_000 })
  const download = page.getByRole('link', { name: 'Download' }).first()
  await expect(download).toBeVisible()
  const href = await download.getAttribute('href')
  const res = await request.get(href!)
  expect(res.status()).toBe(200)
  // Token-less server: no Sign out.
  await expect(page.getByRole('button', { name: 'Sign out' })).toHaveCount(0)

  // Portfolio: the roll-up table renders with the acquisition row.
  await rail(page, 'Portfolio').click()
  await expect(page.getByText('TOTALS BY DEAL TYPE')).toBeVisible({ timeout: 20_000 })
  await expect(page.locator('td', { hasText: 'acquisition' }).first()).toBeVisible()

  // Risk: the Run button exists and a NaN seed is rejected inline.
  await rail(page, 'Risk').click()
  await expect(page.getByRole('button', { name: 'Run simulation' })).toBeVisible()
  const seed = page.getByLabel('Seed (blank = random)')
  await seed.fill('abc')
  await expect(page.getByText('Seed must be a non-negative whole number', { exact: false })).toBeVisible()
  await expect(seed).toHaveAttribute('aria-invalid', 'true')
  await expect(page.getByRole('button', { name: 'Run simulation' })).toBeDisabled()
})

test('compare tab lays two deals side by side with a CSV export', async ({ page, request }) => {
  await createDeal(request, 'Run6 Base')
  await createDeal(request, 'Run6 Tight Cap', { exitCapRatePct: 0.05 })
  // JSON drops undefined: this deal carries no dealType at all.
  await createDeal(request, 'Run6 Untyped', { dealType: undefined })
  await openDeal(page, 'Run6 Base')

  await rail(page, 'Compare').click()
  await page.getByRole('checkbox', { name: /Run6 Base/ }).check()
  await page.getByRole('checkbox', { name: /Run6 Tight Cap/ }).check()

  const table = page.getByRole('table', { name: 'Deal comparison' })
  await expect(table.getByRole('columnheader', { name: /Run6 Base/ })).toBeVisible()
  await expect(table.getByRole('columnheader', { name: /Run6 Tight Cap/ })).toBeVisible()
  // Both columns compute through the native engine (no "not computable").
  await expect(page.getByText('computing…')).toHaveCount(0, { timeout: 20_000 })
  await expect(page.getByText('not computable')).toHaveCount(0)
  const irrRow = table.getByRole('row', { name: /^Levered IRR/ })
  await expect(irrRow.locator('td').nth(0)).toHaveText(/%$/)
  await expect(irrRow.locator('td').nth(1)).toHaveText(/%$/)
  // Direction-aware highlight: exactly one best cell on that row.
  await expect(irrRow.locator('td.bg-emerald-50')).toHaveCount(1)

  const downloadPromise = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV' }).click()
  expect((await downloadPromise).suggestedFilename()).toBe('deal-comparison.csv')

  // An untyped deal is shown as not computable, not as an error.
  await page.getByRole('checkbox', { name: /Run6 Untyped/ }).check()
  await expect(table.getByRole('columnheader', { name: /Run6 Untyped/ })).toContainText('not computable', {
    timeout: 20_000,
  })

  // The selection survives a reload (safeStorage).
  await page.reload()
  await rail(page, 'Compare').click()
  await expect(page.getByRole('checkbox', { name: /Run6 Base/ })).toBeChecked()
})

test('tag round-trip: header chip row, pipeline chips + filter, removal', async ({ page, request }) => {
  const taggedId = await createDeal(request, 'Run6 Tagged')
  await createDeal(request, 'Run6 Plain')
  await openDeal(page, 'Run6 Tagged')

  // Add a tag from the header chip row (Enter commits).
  const tagInput = page.getByRole('textbox', { name: 'Add a tag (press Enter)' })
  await tagInput.fill('Core Plus')
  await tagInput.press('Enter')
  const tagGroup = page.getByRole('group', { name: 'Deal tags' })
  await expect(tagGroup.getByText('Core Plus')).toBeVisible()
  await expect
    .poll(async () => (await (await request.get(`/api/deals/${taggedId}`)).json()).tags as string[])
    .toEqual(['Core Plus'])

  // Pipeline: the row shows the chip; the tag filter narrows the board.
  await rail(page, 'Deals').click()
  const taggedRow = page.locator('tr', { hasText: 'Run6 Tagged' }).first()
  await expect(taggedRow.getByText('Core Plus')).toBeVisible()
  await expect(page.locator('tr', { hasText: 'Run6 Plain' }).first()).toBeVisible()
  await page.getByRole('group', { name: 'Filter by Tags' }).getByRole('button', { name: 'Core Plus' }).click()
  await expect(page.locator('tr', { hasText: 'Run6 Plain' })).toHaveCount(0)
  await expect(taggedRow).toBeVisible()

  // Remove it from the header; the chip and the server copy both clear.
  await rail(page, 'Deal Inputs').click()
  await tagGroup.getByRole('button', { name: 'Remove tag Core Plus' }).click()
  await expect(tagGroup.getByText('Core Plus')).toHaveCount(0)
  await expect
    .poll(async () => (await (await request.get(`/api/deals/${taggedId}`)).json()).tags as string[])
    .toEqual([])
})

test('pipeline: sortable headers, bulk tags, show archived + unarchive', async ({ page, request }) => {
  await createDeal(request, 'Run6 Bravo')
  await createDeal(request, 'Run6 Able')
  const archivedId = await createDeal(request, 'Run6 Shelved')
  expect((await request.post(`/api/deals/${archivedId}/archive`)).ok()).toBeTruthy()
  await openDeal(page, 'Run6 Bravo')
  await rail(page, 'Deals').click()

  // Archived deals are out of the working list until asked for.
  await expect(page.locator('tr', { hasText: 'Run6 Shelved' })).toHaveCount(0)

  // Sortable headers: Deal ascending, then flipped.
  const board = page.getByRole('table', { name: 'Acquisitions' })
  const dealHeader = board.getByRole('columnheader', { name: /^Deal/ })
  await dealHeader.getByRole('button').click()
  await expect(dealHeader).toHaveAttribute('aria-sort', 'ascending')
  const names = () => board.locator('tbody tr td:nth-child(2) button').allTextContents()
  await expect.poll(async () => (await names()).filter((n) => n.startsWith('Run6'))).toEqual(['Run6 Able', 'Run6 Bravo'])
  await dealHeader.getByRole('button').click()
  await expect(dealHeader).toHaveAttribute('aria-sort', 'descending')
  await expect.poll(async () => (await names()).filter((n) => n.startsWith('Run6'))).toEqual(['Run6 Bravo', 'Run6 Able'])
  // A metric column sorts too.
  const irrHeader = board.getByRole('columnheader', { name: /^Levered IRR/ })
  await irrHeader.getByRole('button').click()
  await expect(irrHeader).toHaveAttribute('aria-sort', 'descending')

  // Bulk tag both deals.
  await page.getByRole('checkbox', { name: 'Select Run6 Able' }).check()
  await page.getByRole('checkbox', { name: 'Select Run6 Bravo' }).check()
  await page.getByLabel('Tag to add to or remove from the selection').fill('Watchlist')
  await page.getByRole('button', { name: 'Add tag', exact: true }).click()
  await expect(page.locator('tr', { hasText: 'Run6 Able' }).getByText('Watchlist')).toBeVisible()
  await expect(page.locator('tr', { hasText: 'Run6 Bravo' }).getByText('Watchlist')).toBeVisible()

  // Show archived: dimmed row with Unarchive; unarchiving brings it back.
  await page.getByRole('button', { name: /^Show archived/ }).click()
  const shelved = page.locator('tr[data-archived="true"]', { hasText: 'Run6 Shelved' })
  await expect(shelved).toBeVisible()
  await shelved.getByRole('button', { name: 'Unarchive Run6 Shelved' }).click()
  await expect(page.locator('tr[data-archived="true"]', { hasText: 'Run6 Shelved' })).toHaveCount(0)
  await expect(page.getByRole('checkbox', { name: 'Select Run6 Shelved' })).toBeVisible()
  await expect
    .poll(async () => (await (await request.get(`/api/deals/${archivedId}`)).json()).archivedAt ?? null)
    .toBeNull()
})
