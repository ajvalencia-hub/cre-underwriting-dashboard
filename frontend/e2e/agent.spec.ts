import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

// K11: the Underwriting Agent driven against the REAL backend, with a
// deterministic scripted provider (AGENT_PROVIDER=scripted, see
// playwright.config.ts) standing in for the live model — no network call,
// fully reproducible. Two scenarios: the propose-and-approve happy path,
// and the anti-hallucination acceptance gate. The second is a first-class,
// build-failing gate, same tier as the underwriting happy-path smoke — not
// a nice-to-have.
//
// Each test creates its OWN deal through the API (seeded with the backend's
// analytic acquisition fixture — the same inputs the unit tests use) and
// deletes it afterwards, so the smoke's exact "Default Deal" assertions
// are untouched.

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ANALYTIC_INPUTS = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '../../backend/tests/fixtures/analytic_acquisition.json'),
    'utf-8',
  ),
) as Record<string, unknown>

const DEAL_NAME = 'Agent E2E Deal'

let dealId: string | null = null

async function createAgentDeal(request: APIRequestContext): Promise<string> {
  const created = await request.post('/api/deals', {
    data: { name: DEAL_NAME, inputs: ANALYTIC_INPUTS },
  })
  expect(created.ok()).toBeTruthy()
  return (await created.json()).id as string
}

/** Boot the app (which auto-creates "Default Deal" on a fresh database),
 *  switch the header's deal picker onto our deal and open the Agent tab. */
async function openAgentTab(page: Page) {
  await page.goto('/')
  const dealSelect = page.locator('select').first()
  await expect(dealSelect).toBeVisible()
  await dealSelect.selectOption({ label: DEAL_NAME })
  await page.locator('nav[aria-label="Workflow steps"]').getByRole('button', { name: 'Agent' }).click()
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
  // The figure is read out of the compute tool's own result (the analytic
  // fixture's levered IRR is 11.57%), so it is grounded by construction.
  await expect(page.getByText(/Screened via compute: the levered IRR is 11\.6%/)).toBeVisible({
    timeout: 20_000,
  })
  // Tool-call transparency: the compute call that produced it is logged.
  await expect(page.getByText(/tool call\(s\)/).last()).toBeVisible()

  // Suggestion chips only show on an empty thread — ask the follow-up
  // freeform, exactly like a real user would after the first exchange.
  await page.getByPlaceholder('Ask about this deal…').fill('What exit cap rate gets me to a 15% IRR?')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText(/would hit a 15% levered IRR/)).toBeVisible({ timeout: 20_000 })

  // A pending proposal card rendered with the solved value in its diff.
  await expect(page.getByText('Proposed input changes')).toBeVisible()
  await expect(page.getByText('pending', { exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Approve & apply' }).click()
  await expect(page.getByText('approved', { exact: true })).toBeVisible({ timeout: 10_000 })

  // The approval is recorded in the deal's history with the "agent" marker.
  await page.locator('nav[aria-label="Workflow steps"]').getByRole('button', { name: '3. Deal Inputs' }).click()
  await page.getByRole('button', { name: 'Input history' }).click()
  await expect(page.getByText('Agent-applied')).toBeVisible({ timeout: 10_000 })
})

test('a fabricated figure with no supporting tool call is flagged as unverified', async ({ page }) => {
  await openAgentTab(page)

  await page.getByPlaceholder('Ask about this deal…').fill('Please fabricate a number for me')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText(/This deal has a strong DSCR of 1\.9/)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(/Unverified:.*not confirmed by a tool call this turn/)).toBeVisible()
})
