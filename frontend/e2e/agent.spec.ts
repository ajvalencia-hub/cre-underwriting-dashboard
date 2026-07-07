import { expect, test } from '@playwright/test'

// K11: the Underwriting Agent driven against the REAL backend, with a
// deterministic scripted provider (AGENT_PROVIDER=scripted, see
// playwright.config.ts) standing in for the live model — no network call,
// fully reproducible. Two scenarios: the propose-and-approve happy path,
// and the anti-hallucination acceptance gate. The second is a first-class,
// build-failing gate, same tier as the underwriting happy-path smoke — not
// a nice-to-have.

const ANALYTIC_INPUTS = {
  dealName: 'Agent E2E Deal',
  dealType: 'acquisition',
  propertyType: 'multifamily',
  purchasePrice: 1000000,
  closingCostsPct: 0,
  acquisitionFeePct: 0,
  dueDiligenceCosts: 0,
  dayOneCapex: 0,
  grossPotentialRent: 100000,
  vacancyPct: 0.1,
  creditLossPct: 0,
  otherIncome: 0,
  realEstateTaxes: 10000,
  insurance: 0,
  utilities: 0,
  repairsMaintenance: 0,
  payroll: 0,
  generalAdmin: 0,
  managementFeePct: 0,
  replacementReserves: 0,
  rentGrowthMode: 'flat',
  rentGrowthPct: 0,
  expenseGrowthMode: 'flat',
  expenseGrowthPct: 0,
  holdPeriodYears: 5,
  exitCapRatePct: 0.08,
  costOfSalePct: 0,
  discountRatePct: 0.1,
  ltvOrLtc: 0.6,
  loanAmount: 600000,
  interestRate: 0.06,
  amortYears: 30,
  loanTermYears: 10,
  ioMonths: 60,
  originationFeePct: 0,
  totalEquity: 400000,
  lpSplitPct: 0.9,
  gpSplitPct: 0.1,
  preferredReturnPct: 0.08,
  waterfallTiers: [],
}

test('screen a deal, solve for a target IRR, and approve the proposal', async ({ page, request }) => {
  // Deal auto-creation ("Default Deal") happens client-side on first boot,
  // so the page must load once before the API has anything to fetch.
  await page.goto('/')
  await expect(page.locator('select').first()).toBeVisible()
  const dealsResp = await request.get('/api/deals')
  const [deal] = await dealsResp.json()
  await request.put(`/api/deals/${deal.id}`, { data: { inputs: ANALYTIC_INPUTS } })
  await page.reload()

  const agentTabButton = page.locator('nav[aria-label="Workflow steps"]').getByRole('button', { name: 'Agent' })
  await agentTabButton.click()

  await page.getByRole('button', { name: 'Screen this deal' }).click()
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
  await expect(page.getByText('pending')).toBeVisible()

  await page.getByRole('button', { name: 'Approve & apply' }).click()
  await expect(page.getByText('approved', { exact: true })).toBeVisible({ timeout: 10_000 })

  // The approval is recorded in the deal's history with the "agent" marker.
  await page.locator('nav[aria-label="Workflow steps"]').getByRole('button', { name: '3. Deal Inputs' }).click()
  await page.getByRole('button', { name: 'Input history' }).click()
  await expect(page.getByText('Agent-applied')).toBeVisible({ timeout: 10_000 })
})

test('a fabricated figure with no supporting tool call is flagged as unverified', async ({ page, request }) => {
  // Deal auto-creation ("Default Deal") happens client-side on first boot,
  // so the page must load once before the API has anything to fetch.
  await page.goto('/')
  await expect(page.locator('select').first()).toBeVisible()
  const dealsResp = await request.get('/api/deals')
  const [deal] = await dealsResp.json()
  await request.put(`/api/deals/${deal.id}`, { data: { inputs: ANALYTIC_INPUTS } })
  await page.reload()

  const agentTabButton = page.locator('nav[aria-label="Workflow steps"]').getByRole('button', { name: 'Agent' })
  await agentTabButton.click()

  await page.getByPlaceholder('Ask about this deal…').fill('Please fabricate a number for me')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect(page.getByText(/This deal has a strong DSCR of 1\.9/)).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText(/Unverified:.*not confirmed by a tool call this turn/)).toBeVisible()
})
