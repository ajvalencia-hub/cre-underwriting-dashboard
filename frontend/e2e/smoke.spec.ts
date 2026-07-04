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
  await expect(page.getByText('est.').first()).toBeVisible()

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
