import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// The Underwriting Agent driven against the REAL backend, with the
// deterministic scripted provider (AGENT_PROVIDER=scripted, see
// playwright.config.ts) standing in for a live model — no network call,
// fully reproducible. Two scenarios: propose-and-approve, and the
// anti-hallucination gate (a figure no tool call produced is flagged).
//
// Each test creates its OWN deal through the API (seeded with the backend's
// analytic acquisition fixture, the inputs the unit tests use) and deletes
// it afterwards, so the smoke's exact "Default Deal" assertions hold.

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ANALYTIC_INPUTS = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '../../backend/tests/fixtures/analytic_acquisition.json'), 'utf-8'),
) as Record<string, unknown>
delete ANALYTIC_INPUTS._comment

const DEAL_NAME = 'Agent E2E Deal'

let dealId: string | null = null

async function createAgentDeal(request: APIRequestContext): Promise<string> {
  const created = await request.post('/api/deals', { data: { name: DEAL_NAME, inputs: ANALYTIC_INPUTS } })
  expect(created.ok()).toBeTruthy()
  return (await created.json()).id as string
}

/** Boot the app, switch the header's deal picker onto our deal and open the
 *  Agent tab from the left rail. */
async function openAgentTab(page: Page) {
  await page.goto('/')
  const dealSelect = page.locator('select').first()
  await expect(dealSelect).toBeVisible()
  await dealSelect.selectOption({ label: DEAL_NAME })
  await page.getByRole('button', { name: 'Agent', exact: true }).click()
  await expect(page.getByPlaceholder('Ask about this deal…')).toBeEnabled()
}

test.beforeEach(async ({ request }) => {
  dealId = await createAgentDeal(request)
})

test.afterEach(async ({ request }) => {
  if (dealId) await request.delete(`/api/deals/${dealId}`)
  dealId = null
})

test('screen a deal, solve for a target IRR, and approve the proposal', async ({ page }) => {
  await openAgentTab(page)

  await page.getByRole('button', { name: 'Screen this deal' }).click()
  // The figure is read out of the compute tool's own result, so it is
  // grounded by construction.
  await expect(page.getByText(/Screened via compute: the levered IRR is -?\d+\.\d%/)).toBeVisible({ timeout: 20_000 })
  // Tool-call transparency: the compute call that produced it is logged.
  await expect(page.getByText(/tool call\(s\)/).last()).toBeVisible()

  // Suggestion chips only show on an empty thread — ask the follow-up
  // freeform, like a real user after the first exchange.
  await page.getByPlaceholder('Ask about this deal…').fill('What exit cap rate gets me to a 15% IRR?')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText(/would hit a 15% levered IRR/)).toBeVisible({ timeout: 20_000 })

  // A pending proposal card with the solved value in its diff.
  const card = page.getByTestId('agent-proposal')
  await expect(card.getByText('Proposed input changes')).toBeVisible()
  await expect(card.getByText('Pending review', { exact: true })).toBeVisible()

  // Approve goes through App (IC lock, save flush, provenance).
  await card.getByRole('button', { name: 'Approve & apply' }).click()
  await expect(card.getByText('Approved', { exact: true })).toBeVisible({ timeout: 10_000 })

  // The approval is recorded in the deal's history with the "agent" marker.
  await page.getByRole('button', { name: 'Deal Inputs', exact: true }).click()
  await page.getByRole('button', { name: 'Input history' }).click()
  await expect(page.getByText('Agent-applied').first()).toBeVisible({ timeout: 10_000 })
})

test('a fabricated figure with no supporting tool call is flagged as unverified', async ({ page }) => {
  await openAgentTab(page)

  await page.getByPlaceholder('Ask about this deal…').fill('Please fabricate a number for me')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText(/This deal has a strong DSCR of 1\.9/)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(/Unverified:.*not confirmed by a tool call this turn/)).toBeVisible()
})

test('the floating dock carries the same conversation and closes on Escape', async ({ page }) => {
  await openAgentTab(page)
  await page.getByPlaceholder('Ask about this deal…').fill('Please fabricate a number for me')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText(/This deal has a strong DSCR of 1\.9/)).toBeVisible({ timeout: 20_000 })

  // The dock is hidden while the Agent tab shows; on another tab it opens
  // onto the same thread.
  await expect(page.getByRole('button', { name: 'Toggle underwriting agent chat' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Deal Inputs', exact: true }).click()
  await page.getByRole('button', { name: 'Toggle underwriting agent chat' }).click()
  const dock = page.getByRole('dialog', { name: 'Underwriting agent chat' })
  await expect(dock.getByText(/This deal has a strong DSCR of 1\.9/)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dock).toBeHidden()
})
