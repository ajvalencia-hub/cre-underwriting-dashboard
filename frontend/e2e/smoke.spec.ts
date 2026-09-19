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

  // Native compute populates the sidebar with 'native'-tagged metrics.
  await page.getByRole('button', { name: 'Compute (native)' }).click()
  await expect(page.getByText('native', { exact: true }).first()).toBeVisible({ timeout: 20_000 })

  // Cash Flow tab renders the statement.
  await page.getByRole('button', { name: '4. Cash Flow' }).click()
  await expect(page.getByText('Net operating income')).toBeVisible()
  await expect(page.getByText('Export annual CSV')).toBeVisible()

  // Save two scenarios (native-era: no template required). All tabs stay
  // mounted, and the Quick Screen has its own "Scenario name" input — the
  // Scenarios panel's is the last in DOM order.
  await page.getByRole('button', { name: '6. Scenarios' }).click()
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

  // Deals (pipeline) tab: one board per dealflow, each with its own stage
  // chips and typed "New … deal" button.
  await page.getByRole('button', { name: 'Deals' }).click()
  await expect(page.getByText(/Screening · \d/)).toHaveCount(2)
  // exact: the header's own "New Deal" button is a different control
  await expect(page.getByRole('button', { name: 'New acquisition deal', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'New development deal', exact: true })).toBeVisible()

  // The auto-created Default Deal predates typed creation and waits in the
  // untyped list; a typed deal created from the board is a row immediately.
  await expect(page.getByText('UNTYPED DEALS — assign a dealflow')).toBeVisible()
  await page.getByRole('button', { name: 'New acquisition deal', exact: true }).click()
  const dealRow = page.locator('tr', { hasText: 'Untitled Acquisition' }).first()
  await expect(dealRow).toBeVisible()

  // Status select persists a stage change.
  await dealRow.locator('select').selectOption('underwriting')
  await expect(page.getByText(/Underwriting · 1/)).toBeVisible()

  // Read-only HTML share responds with a self-contained page for the deal.
  const shareHref = await dealRow.locator('a', { hasText: 'Share' }).getAttribute('href')
  const shareResponse = await request.get(shareHref!)
  expect(shareResponse.status()).toBe(200)
  expect(await shareResponse.text()).toContain('Read-only')

  // Comps tab: importer present, inline add round-trip.
  await page.getByRole('button', { name: '7. Comps' }).click()
  await expect(page.getByText('Import CSV (Yardi Matrix export)')).toBeVisible()
  await page.getByPlaceholder('New comp name').fill('Smoke Comp')
  await page.getByPlaceholder('Price').fill('1000000')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.locator('td', { hasText: 'Smoke Comp' }).first()).toBeVisible()

  // Deal Inputs: presets bar and history drawer are mounted.
  await page.getByRole('button', { name: '3. Deal Inputs' }).click()
  await expect(page.getByText('ASSUMPTION PRESETS')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Input history' })).toBeVisible()
})

// Assigning a dealflow to the ACTIVE untyped deal. Regression canary for two
// bugs: choosing "Acquisition" never persisted (the schema default already put
// dealType=acquisition in the hydrated form, so autosave saw no diff), and the
// board didn't move the deal — then a stage change replaced it with the stale
// server copy and it fell back into the untyped list.
//
// Self-contained and LAST in this file: specs share one scratch db per run and
// the tests above assume a fresh one (only the Default Deal), so this creates
// and activates its own untyped deal after they have run.
test('active untyped deal moves boards and keeps its dealflow', async ({ page, request }) => {
  const name = `Untyped ${Date.now()}`
  const created = await (await request.post('/api/deals', { data: { name } })).json()
  expect(created.inputs?.dealType).toBeUndefined()
  await page.addInitScript((id) => localStorage.setItem('cre-active-deal-id', id), created.id)

  await page.goto('/')
  await expect(page.locator('select').first()).toBeVisible()
  await page.getByRole('button', { name: 'Deals' }).click()

  const untypedItem = page.locator('li', { hasText: name })
  await untypedItem.getByRole('button', { name: 'Acquisition', exact: true }).click()

  // Moves to the Acquisitions board immediately, no reload.
  await expect(untypedItem).toHaveCount(0)
  const dealRow = page.locator('tr', { hasText: name }).first()
  await expect(dealRow).toBeVisible()

  // A stage change right away (inside the autosave debounce) keeps the type.
  await dealRow.locator('select').selectOption('underwriting')
  await expect(dealRow.locator('select')).toHaveValue('underwriting')
  await expect(untypedItem).toHaveCount(0)
  await expect(dealRow).toBeVisible()

  // ...and both were persisted server-side.
  const saved = await (await request.get(`/api/deals/${created.id}`)).json()
  expect(saved.inputs.dealType).toBe('acquisition')
  expect(saved.status).toBe('underwriting')
})
