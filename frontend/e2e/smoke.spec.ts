import { expect, test, type Locator, type Page } from '@playwright/test'

// One happy path through the real stack — a canary, not a suite:
// deal auto-creation → quick screen (verdict + sidebar estimates) → send to
// deal inputs → native compute → cash flow tab → save two scenarios →
// comparison view → IC memo download.

function inputNextToLabel(page: Page, labelText: string): Locator {
  return page
    .locator('label', { hasText: labelText })
    .first()
    .locator('xpath=..')
    .locator('input')
    .first()
}

test('underwriting happy path', async ({ page }) => {
  // Confirmations (e.g. Send to Deal Inputs replacing existing values) are
  // accepted — this path intends every change it makes.
  page.on('dialog', (dialog) => void dialog.accept())
  await page.goto('/')

  // A "Default Deal" is created automatically on first boot.
  await expect(page.locator('select').first()).toBeVisible()
  await expect(page.locator('select').first().locator('option')).toHaveText(['Default Deal'])

  // Quick Screen renders a feasibility verdict and the sidebar shows
  // Quick Screen estimates marked "est.".
  await expect(page.getByText(/Strong —|Marginal —|Weak —/).first()).toBeVisible()
  // exact: the (hidden, always-mounted) Settings page has prose ending in
  // "…manifest." that a substring match would pick up first.
  await expect(page.getByText('est.', { exact: true }).first()).toBeVisible()

  // Nudge the rent input and confirm the verdict block is still live.
  const rentInput = inputNextToLabel(page, 'Monthly Rent per Unit')
  await rentInput.fill('2,400')
  await rentInput.blur()
  await expect(page.getByText(/Strong —|Marginal —|Weak —/).first()).toBeVisible()

  // Send to Deal Inputs (maps the napkin onto a development deal).
  await page.getByRole('button', { name: /Send to Deal Inputs/ }).click()
  await expect(page.getByRole('button', { name: 'Compute (native)' })).toBeVisible()

  // Native compute populates the sidebar with 'engine'-tagged metrics and
  // marks them current.
  await page.getByRole('button', { name: 'Compute (native)' }).click()
  await expect(page.getByText('engine', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('Current', { exact: true })).toBeVisible()

  // Cash Flow tab renders the statement.
  await page.getByRole('button', { name: 'Cash Flow', exact: true }).click()
  await expect(page.getByText('Net operating income')).toBeVisible()
  await expect(page.getByText('Export annual CSV')).toBeVisible()

  // Save two scenarios (native-era: no template required). All tabs stay
  // mounted, and the Quick Screen has its own "Scenario name" input — the
  // Scenarios panel's is the last in DOM order.
  await page.getByRole('button', { name: 'Scenarios', exact: true }).click()
  const nameInput = page.getByPlaceholder('Scenario name').last()
  await nameInput.fill('Base Case')
  await page.getByRole('button', { name: 'Save current inputs as scenario' }).click()
  await expect(
    page.locator('li', { hasText: 'Base Case' }).first(),
  ).toBeVisible({ timeout: 15_000 })

  await nameInput.fill('Upside')
  await page.getByRole('button', { name: 'Save current inputs as scenario' }).click()
  await expect(page.locator('li', { hasText: 'Upside' }).first()).toBeVisible({ timeout: 15_000 })

  // Compare the two — the comparison view renders with the outputs table.
  const saved = page.locator('section', { hasText: 'SAVED SCENARIOS' })
  await saved.locator('input[type=checkbox]').nth(0).check()
  await saved.locator('input[type=checkbox]').nth(1).check()
  await expect(page.getByText(/COMPARISON \(2 of/)).toBeVisible()
  await expect(page.getByText('OUTPUTS — best value highlighted', { exact: false })).toBeVisible()

  // IC memo downloads as a .docx.
  const downloadPromise = page.waitForEvent('download')
  await page
    .locator('li', { hasText: 'Base Case' })
    .first()
    .getByRole('button', { name: 'Generate IC Memo' })
    .click()
  const download = await downloadPromise
  expect(download.suggestedFilename()).toMatch(/\.docx$/)
})

// H13 extension: the Run-3 surfaces — pipeline home, comps database, presets
// bar, input history, and the read-only HTML share endpoint.
test('pipeline, comps, presets, and share surfaces', async ({ page, request }) => {
  await page.goto('/')
  await expect(page.locator('select').first()).toBeVisible()

  // Deals (pipeline) tab. The auto-created deal starts untyped (it predates
  // typed creation); assigning it a dealflow puts it on the Acquisitions
  // board, whose stage chips then count it.
  await page.getByRole('button', { name: 'Deals', exact: true }).click()
  await page.locator('li', { hasText: 'Default Deal' }).getByRole('button', { name: 'Acquisition', exact: true }).click()
  await expect(page.getByText('Screening · 1', { exact: true })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('button', { name: 'New acquisition deal' })).toBeVisible()
  const dealRow = page.locator('tr', { hasText: 'Default Deal' }).first()
  await expect(dealRow).toBeVisible()

  // Status select persists a stage change.
  await dealRow.locator('select').selectOption('underwriting')
  await expect(page.getByText('Underwriting · 1', { exact: true })).toBeVisible()

  // Read-only HTML share responds with a self-contained page for the deal.
  const shareHref = await dealRow.locator('a', { hasText: 'Share' }).getAttribute('href')
  const shareResponse = await request.get(shareHref!)
  expect(shareResponse.status()).toBe(200)
  expect(await shareResponse.text()).toContain('Read-only')

  // Comps tab: importer present, inline add round-trip.
  await page.getByRole('button', { name: 'Comps', exact: true }).click()
  await expect(page.getByText('Import CSV (Yardi Matrix export)')).toBeVisible()
  await page.getByPlaceholder('New comp name').fill('Smoke Comp')
  await page.getByPlaceholder('Price').fill('1000000')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.locator('td', { hasText: 'Smoke Comp' }).first()).toBeVisible()

  // Deal Inputs: presets bar and history drawer are mounted.
  await page.getByRole('button', { name: 'Deal Inputs', exact: true }).click()
  await expect(page.getByText('ASSUMPTION PRESETS')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Input history' })).toBeVisible()
})

test('command palette jumps to a field and runs Compute', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('select').first()).toBeVisible()

  // Roadmap #30: ⌘K → a Deal Inputs field by name → focused on its tab.
  await page.keyboard.press('ControlOrMeta+k')
  await page.getByRole('textbox', { name: 'Command or search' }).fill('exit cap')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Deal Inputs', exact: true })).toHaveAttribute('aria-current', 'page')
  await expect(page.locator('#field-exitCapRatePct input').first()).toBeFocused()

  // ⌘K → "compute" runs the pro forma: the summary reports a current result
  // or, for a deal still missing inputs, the failed compute naming them.
  await page.keyboard.press('ControlOrMeta+k')
  await page.getByRole('textbox', { name: 'Command or search' }).fill('compute')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Command palette' })).toBeHidden()
  await expect(page.getByText(/^(Current|Last compute failed\.)$/).first()).toBeVisible({ timeout: 20_000 })
})

test('investment committee: submit locks the inputs, reopen with a reason unlocks them', async ({ page }) => {
  page.on('dialog', (dialog) => void dialog.accept())
  await page.goto('/')
  await expect(page.locator('select').first()).toBeVisible()

  // A deal that computes: send the Quick Screen to Deal Inputs.
  await page.getByRole('button', { name: 'Quick Screen', exact: true }).click()
  await page.getByRole('button', { name: /Send to Deal Inputs/ }).click()
  await expect(page.getByRole('button', { name: 'Compute (native)' })).toBeVisible()

  await page.getByRole('button', { name: 'IC Approval', exact: true }).click()
  await page.getByLabel('Your name').fill('Ana Analyst')
  await page.getByRole('button', { name: 'Submit to IC' }).click()
  await expect(page.getByText('0 of 1 approval. Inputs are locked.')).toBeVisible()
  await expect(page.getByText('Ana Analyst submitted to IC (1 approval needed)')).toBeVisible()

  // Deal Inputs are read-only while it's with the committee.
  await page.getByRole('button', { name: 'Deal Inputs', exact: true }).click()
  await expect(page.getByText(/these inputs are locked/)).toBeVisible()
  await expect(page.locator('#field-exitCapRatePct input').first()).toBeDisabled()

  // Reopening needs a reason; then the inputs are editable again.
  await page.getByRole('button', { name: 'IC Approval', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Reopen for edits' })).toBeDisabled()
  await page.getByLabel('Comment or reason').fill('Revisit the exit cap')
  await page.getByRole('button', { name: 'Reopen for edits' }).click()
  await expect(page.getByText('Ana Analyst reopened it for edits')).toBeVisible()
  await page.getByRole('button', { name: 'Deal Inputs', exact: true }).click()
  await expect(page.locator('#field-exitCapRatePct input').first()).toBeEnabled()
})
