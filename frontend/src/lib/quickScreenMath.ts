// Pure calculation module for the Back-of-Napkin Quick Screen. Every formula the
// panel and the summary sidebar display lives here — components only format and
// render these results, never recompute them.

export type SizeMode = 'units' | 'sf'
export type DealMode = 'development' | 'acquisition'
export type FeasibilityTier = 'strong' | 'marginal' | 'weak'

export interface FeasibilityThresholds {
  /** Spread over exit cap (bps) at/above which the deal is "strong". */
  strong: number
  /** Spread over exit cap (bps) at/above which the deal is "marginal" (below strong). */
  marginal: number
}

export const FEASIBILITY_THRESHOLDS: FeasibilityThresholds = {
  strong: 150,
  marginal: 100,
}

export function classifyFeasibility(
  spreadBps: number,
  thresholds: FeasibilityThresholds = FEASIBILITY_THRESHOLDS,
): FeasibilityTier {
  if (spreadBps >= thresholds.strong) return 'strong'
  if (spreadBps >= thresholds.marginal) return 'marginal'
  return 'weak'
}

/** Vacancy assumed when the NOI-margin detail disclosure is collapsed, purely for
 *  decomposing the single margin input into an implied opex/unit and NOI/unit. */
export const DEFAULT_IMPLIED_VACANCY_PCT = 0.05

/** Assumed average unit size, used only to render a $/SF <-> $/unit conversion
 *  hint under the hard-cost and rent fields — never fed into the math. */
export const QUICK_SCREEN_SF_PER_UNIT_ASSUMPTION = 900

export interface QuickScreenInputs {
  dealMode: DealMode
  sizeMode: SizeMode
  quantity: number // # units, or total SF

  // Development-mode cost basis (ignored when dealMode === 'acquisition')
  landCost: number
  hardCostPerUnit: number // $ per unit or per SF, depending on sizeMode
  softCostPct: number // fraction, e.g. 0.20 = 20% of hard cost
  contingencyPct: number // fraction, of (hard + soft)

  // Acquisition-mode cost basis (ignored when dealMode === 'development')
  purchasePricePerUnit: number // $ per unit or per SF, depending on sizeMode
  closingCostsPct: number // fraction of purchase price
  renoBudgetPerUnit: number // $ per unit or per SF — optional value-add capex, 0 = as-is

  rent: number // $/unit/month if sizeMode === 'units', else $/SF/year
  noiMarginPct: number // fraction of gross potential rent retained as NOI (simple mode)
  exitCapRatePct: number // fraction
  ltcPct: number // fraction, 0 disables leverage output
  constructionInterestRatePct: number // fraction, interest-only approximation (labeled "loan rate" for acquisitions)
  useDetailedNoi: boolean // when true, vacancyPct/opexRatioPct drive NOI instead of noiMarginPct
  vacancyPct: number // fraction of gross potential rent lost to vacancy (detail mode)
  opexRatioPct: number // fraction of effective gross income spent on opex (detail mode)
}

/** Derives the opex ratio (of EGI) that, combined with the given vacancy assumption,
 *  reproduces a target NOI margin (of GPR) exactly. Used both by the simple-mode NOI
 *  calc and by the UI when a user opens the detail disclosure for the first time. */
export function deriveOpexRatioFromMargin(noiMarginPct: number, vacancyPct: number): number {
  const occupied = 1 - vacancyPct
  if (occupied <= 0) return 0
  return 1 - noiMarginPct / occupied
}

export interface QuickScreenResults {
  // Development-mode cost breakdown (0 in acquisition mode)
  hardCosts: number
  softCosts: number
  contingency: number
  // Acquisition-mode cost breakdown (0 in development mode)
  purchasePrice: number
  closingCosts: number
  renoBudget: number
  // Mode-agnostic total: land+hard+soft+contingency (development), or
  // purchasePrice*(1+closingCostsPct)+renoBudget (acquisition).
  totalCost: number

  grossPotentialRent: number
  vacancyLoss: number
  effectiveGrossIncome: number
  operatingExpenses: number
  opexPerUnit: number
  noiPerUnit: number
  effectiveNoiMarginPct: number
  stabilizedNoi: number
  stabilizedValue: number

  profit: number
  profitMarginPct: number
  yieldOnCost: number
  goingInCapRate: number
  capRateSpreadBps: number
  feasibility: FeasibilityTier

  loanAmount: number
  equityRequired: number
  annualDebtService: number
  leveredCashFlow: number
  cashOnCashPct: number | null
  debtYield: number | null
  loanConstant: number | null
  breakEvenRatio: number
  minDscr: number | null
  avgDscr: number | null

  terminalValue: number
  netSaleProceeds: number
  totalProfit: number
}

export function computeQuickScreen(inputs: QuickScreenInputs): QuickScreenResults {
  // Checked against 'acquisition' specifically (not `!== 'development'`) so a
  // scenario/URL saved before dealMode existed — where it's undefined —
  // reproduces the original development-only behavior exactly.
  const isAcquisition = inputs.dealMode === 'acquisition'

  let hardCosts = 0
  let softCosts = 0
  let contingency = 0
  let purchasePrice = 0
  let closingCosts = 0
  let renoBudget = 0
  let totalCost: number

  if (isAcquisition) {
    purchasePrice = inputs.quantity * inputs.purchasePricePerUnit
    closingCosts = purchasePrice * inputs.closingCostsPct
    renoBudget = inputs.quantity * inputs.renoBudgetPerUnit
    totalCost = purchasePrice + closingCosts + renoBudget
  } else {
    hardCosts = inputs.quantity * inputs.hardCostPerUnit
    softCosts = hardCosts * inputs.softCostPct
    contingency = (hardCosts + softCosts) * inputs.contingencyPct
    totalCost = inputs.landCost + hardCosts + softCosts + contingency
  }

  const grossPotentialRent =
    inputs.sizeMode === 'units' ? inputs.quantity * inputs.rent * 12 : inputs.quantity * inputs.rent

  const vacancyPct = inputs.useDetailedNoi ? inputs.vacancyPct : DEFAULT_IMPLIED_VACANCY_PCT
  const opexRatioPct = inputs.useDetailedNoi
    ? inputs.opexRatioPct
    : deriveOpexRatioFromMargin(inputs.noiMarginPct, vacancyPct)

  const vacancyLoss = grossPotentialRent * vacancyPct
  const effectiveGrossIncome = grossPotentialRent - vacancyLoss
  const operatingExpenses = effectiveGrossIncome * opexRatioPct
  const stabilizedNoi = effectiveGrossIncome - operatingExpenses
  const effectiveNoiMarginPct = grossPotentialRent > 0 ? stabilizedNoi / grossPotentialRent : 0

  const opexPerUnit = inputs.quantity > 0 ? operatingExpenses / inputs.quantity : 0
  const noiPerUnit = inputs.quantity > 0 ? stabilizedNoi / inputs.quantity : 0

  const stabilizedValue = inputs.exitCapRatePct > 0 ? stabilizedNoi / inputs.exitCapRatePct : 0

  const profit = stabilizedValue - totalCost
  const profitMarginPct = totalCost > 0 ? profit / totalCost : 0

  const yieldOnCost = totalCost > 0 ? stabilizedNoi / totalCost : 0
  // Development: no separate acquisition price exists for a ground-up deal —
  // the cost basis doubles as the "going-in" basis, so going-in cap rate
  // collapses to yield on cost. Acquisition: going-in cap is priced off the
  // purchase price alone, excluding closing costs and any renovation budget —
  // that's what makes it meaningfully different from yield on cost (the
  // full-cost basis) for a value-add deal.
  const goingInCapRate = isAcquisition
    ? purchasePrice > 0
      ? stabilizedNoi / purchasePrice
      : 0
    : yieldOnCost
  const capRateSpreadBps = (yieldOnCost - inputs.exitCapRatePct) * 10000
  const feasibility = classifyFeasibility(capRateSpreadBps)

  const loanAmount = totalCost * inputs.ltcPct
  const equityRequired = totalCost - loanAmount
  const annualDebtService = loanAmount * inputs.constructionInterestRatePct
  const leveredCashFlow = stabilizedNoi - annualDebtService
  const cashOnCashPct = equityRequired > 0 ? leveredCashFlow / equityRequired : null

  const debtYield = loanAmount > 0 ? stabilizedNoi / loanAmount : null
  // Interest-only approximation: debt service is pure interest, so the loan
  // constant collapses to the interest rate exactly (no amortization modeled).
  const loanConstant = loanAmount > 0 ? annualDebtService / loanAmount : null
  // Break-even ratio = (opex + debt service) / GPR, where "opex" here means
  // everything that isn't NOI (GPR - NOI) — mode-agnostic, so it's unaffected
  // by whether the vacancy/opex detail disclosure is open.
  const breakEvenRatio =
    grossPotentialRent > 0
      ? (grossPotentialRent - stabilizedNoi + annualDebtService) / grossPotentialRent
      : 0
  const minDscr = loanAmount > 0 && annualDebtService > 0 ? stabilizedNoi / annualDebtService : null
  // Single stabilized year, interest-only debt service — min and avg DSCR are
  // identical under this approximation (no amortization schedule to vary across years).
  const avgDscr = minDscr

  // Exit assumed simultaneous with stabilization; no disposition/selling costs
  // modeled, and loan payoff equals the interest-only balance (no amortization).
  const terminalValue = stabilizedValue
  const netSaleProceeds = terminalValue - loanAmount
  const totalProfit = profit

  return {
    hardCosts,
    softCosts,
    contingency,
    purchasePrice,
    closingCosts,
    renoBudget,
    totalCost,
    grossPotentialRent,
    vacancyLoss,
    effectiveGrossIncome,
    operatingExpenses,
    opexPerUnit,
    noiPerUnit,
    effectiveNoiMarginPct,
    stabilizedNoi,
    stabilizedValue,
    profit,
    profitMarginPct,
    yieldOnCost,
    goingInCapRate,
    capRateSpreadBps,
    feasibility,
    loanAmount,
    equityRequired,
    annualDebtService,
    leveredCashFlow,
    cashOnCashPct,
    debtYield,
    loanConstant,
    breakEvenRatio,
    minDscr,
    avgDscr,
    terminalValue,
    netSaleProceeds,
    totalProfit,
  }
}

export const QUICK_SCREEN_DEFAULTS: QuickScreenInputs = {
  dealMode: 'development',
  sizeMode: 'units',
  quantity: 100,
  landCost: 3_000_000,
  hardCostPerUnit: 180_000,
  softCostPct: 0.2,
  contingencyPct: 0.05,
  purchasePricePerUnit: 220_000,
  closingCostsPct: 0.02,
  renoBudgetPerUnit: 0,
  rent: 1_800,
  noiMarginPct: 0.6,
  exitCapRatePct: 0.055,
  ltcPct: 0.6,
  constructionInterestRatePct: 0.075,
  useDetailedNoi: false,
  vacancyPct: DEFAULT_IMPLIED_VACANCY_PCT,
  opexRatioPct: deriveOpexRatioFromMargin(0.6, DEFAULT_IMPLIED_VACANCY_PCT),
}

// ---------------------------------------------------------------------------
// Per-field validation ranges + arrow-key step sizes. A settings object, not
// hardcoded inline in the input components.
// ---------------------------------------------------------------------------

export interface QuickScreenFieldConfig {
  min?: number
  max?: number
  step: number
}

export const QUICK_SCREEN_FIELD_CONFIG: Record<string, QuickScreenFieldConfig> = {
  quantity: { min: 1, step: 1 },
  landCost: { min: 0, step: 5_000 },
  hardCostPerUnit: { min: 0, step: 1_000 },
  softCostPct: { min: 0, max: 1, step: 0.01 },
  contingencyPct: { min: 0, max: 1, step: 0.01 },
  purchasePricePerUnit: { min: 0, step: 5_000 },
  closingCostsPct: { min: 0, max: 0.1, step: 0.005 },
  renoBudgetPerUnit: { min: 0, step: 500 },
  rent: { min: 0, step: 25 },
  noiMarginPct: { min: 0, max: 1, step: 0.01 },
  vacancyPct: { min: 0, max: 1, step: 0.0025 },
  opexRatioPct: { min: 0, max: 1, step: 0.01 },
  exitCapRatePct: { min: 0.03, max: 0.12, step: 0.0025 },
  ltcPct: { min: 0, max: 0.85, step: 0.01 },
  constructionInterestRatePct: { min: 0, max: 0.2, step: 0.0025 },
}

// ---------------------------------------------------------------------------
// Solve-for: closed-form "what would it take to hit a target spread (bps)".
// All three exploit the fact that yield on cost = stabilizedNoi / TDC is
// linear/separable in each variable, so no iteration is needed — see the
// algebra documented above each function.
// ---------------------------------------------------------------------------

/**
 * Rent: NOI is proportional to GPR (NOI = GPR * effectiveNoiMarginPct), and GPR
 * is proportional to rent (GPR = quantity * annualFactor * rent), so NOI is
 * linear in rent. Solve NOI_target = TDC * (exitCap + targetSpread) for rent:
 *   rent = NOI_target / (effectiveNoiMarginPct * quantity * annualFactor)
 */
export function solveRentForSpread(inputs: QuickScreenInputs, targetBps: number): number | null {
  const targetSpreadFraction = targetBps / 10000
  const results = computeQuickScreen(inputs)
  const annualFactor = inputs.sizeMode === 'units' ? 12 : 1
  if (inputs.quantity <= 0 || annualFactor <= 0 || results.effectiveNoiMarginPct <= 0) return null

  const requiredNoi = results.totalCost * (inputs.exitCapRatePct + targetSpreadFraction)
  const requiredGpr = requiredNoi / results.effectiveNoiMarginPct
  return requiredGpr / (inputs.quantity * annualFactor)
}

/**
 * Hard cost/unit (development mode): NOI doesn't depend on hard cost, so solve
 * for the total cost that produces the target yield on cost
 * (cost_target = NOI / (exitCap + targetSpread)), then invert
 * cost = land + hard*(1+softCostPct)*(1+contingencyPct) for hard cost:
 *   hardCostPerUnit = (cost_target - land) / ((1+softCostPct)*(1+contingencyPct)*quantity)
 */
export function solveHardCostForSpread(inputs: QuickScreenInputs, targetBps: number): number | null {
  const targetSpreadFraction = targetBps / 10000
  const results = computeQuickScreen(inputs)
  const costMultiplier = (1 + inputs.softCostPct) * (1 + inputs.contingencyPct)
  if (results.stabilizedNoi <= 0 || costMultiplier <= 0 || inputs.quantity <= 0) return null

  const costTarget = results.stabilizedNoi / (inputs.exitCapRatePct + targetSpreadFraction)
  const requiredHardCosts = (costTarget - inputs.landCost) / costMultiplier
  return requiredHardCosts > 0 ? requiredHardCosts / inputs.quantity : null
}

/**
 * Purchase price/unit (acquisition mode): mirrors solveHardCostForSpread —
 * NOI doesn't depend on purchase price, so solve for the total cost that
 * produces the target yield on cost, then invert
 * cost = purchasePrice*(1+closingCostsPct) + renoBudget for purchase price:
 *   purchasePricePerUnit = (cost_target - renoBudget) / ((1+closingCostsPct)*quantity)
 */
export function solvePurchasePriceForSpread(inputs: QuickScreenInputs, targetBps: number): number | null {
  const targetSpreadFraction = targetBps / 10000
  const results = computeQuickScreen(inputs)
  const costMultiplier = 1 + inputs.closingCostsPct
  if (results.stabilizedNoi <= 0 || costMultiplier <= 0 || inputs.quantity <= 0) return null

  const costTarget = results.stabilizedNoi / (inputs.exitCapRatePct + targetSpreadFraction)
  const requiredPurchasePrice = (costTarget - results.renoBudget) / costMultiplier
  return requiredPurchasePrice > 0 ? requiredPurchasePrice / inputs.quantity : null
}

/**
 * Exit cap: yield on cost = NOI / TDC doesn't depend on exit cap at all, so
 * this is a direct algebraic solve of spread = yieldOnCost - exitCap:
 *   exitCap = yieldOnCost - targetSpread
 */
export function solveExitCapForSpread(inputs: QuickScreenInputs, targetBps: number): number | null {
  const targetSpreadFraction = targetBps / 10000
  const results = computeQuickScreen(inputs)
  const solvedCap = results.yieldOnCost - targetSpreadFraction
  return solvedCap > 0 ? solvedCap : null
}

// ---------------------------------------------------------------------------
// Sidebar wiring: map the quick-screen result set onto the shared output-metric
// schema ids (see backend/app/data/input_schema.json `outputs`).
// ---------------------------------------------------------------------------

/** Metric ids the quick screen can genuinely compute. */
export const QUICK_SCREEN_DERIVABLE_OUTPUT_IDS = [
  'goingInCapRate',
  'yieldOnCost',
  'developmentSpreadBps',
  'terminalValue',
  'totalProfit',
  'ltc',
  'debtYield',
  'loanConstant',
  'breakEvenRatio',
  'minDscr',
  'avgDscr',
  'stabilizedCashOnCash',
] as const

/** Metric ids that genuinely require the full multi-year/waterfall model. */
export const QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS = [
  'unleveredIrr',
  'leveredIrr',
  'lpIrr',
  'gpIrr',
  'equityMultiple',
  'unleveredEquityMultiple',
  'lpEquityMultiple',
  'moic',
  'avgCashOnCash',
  'cashOnCashYear1',
  'annualizedReturn',
  'paybackPeriodYears',
  'npv',
  'profitabilityIndex',
  'breakEvenOccupancy',
  'interestCoverageRatio',
] as const

export function mapQuickScreenToOutputMetrics(
  results: QuickScreenResults,
  inputs: QuickScreenInputs,
): Record<string, number> {
  const out: Record<string, number> = {}
  const set = (id: string, value: number | null) => {
    if (value !== null && Number.isFinite(value)) out[id] = value
  }
  set('goingInCapRate', results.goingInCapRate)
  set('yieldOnCost', results.yieldOnCost)
  set('developmentSpreadBps', results.capRateSpreadBps / 10000) // schema declares this metric as type "percent"
  set('terminalValue', results.terminalValue)
  set('totalProfit', results.totalProfit)
  set('ltc', inputs.ltcPct)
  set('debtYield', results.debtYield)
  set('loanConstant', results.loanConstant)
  set('breakEvenRatio', results.breakEvenRatio)
  set('minDscr', results.minDscr)
  set('avgDscr', results.avgDscr)
  set('stabilizedCashOnCash', results.cashOnCashPct)
  return out
}

/**
 * Shared mapping from quick-screen state onto the Deal Inputs field ids (see
 * backend/app/data/input_schema.json) — the single implementation behind
 * "Send to Deal Inputs" and "Save as Scenario". Branches on dealMode; the
 * shared fields (rent, vacancy, exit cap, financing, equity) are identical
 * either way — only the cost-basis section differs.
 *
 * NOT mapped, and why (applies to both modes unless noted):
 *  - propertyType / mixedUseComponents — sizeMode ('units' vs 'sf') doesn't
 *    reliably imply a property type (SF-denominated could be office, retail,
 *    industrial, etc.), so guessing would be worse than leaving it blank.
 *  - operating_expenses.* (realEstateTaxes, insurance, utilities,
 *    repairsMaintenance, payroll, generalAdmin, managementFeePct,
 *    replacementReserves) — the quick screen only produces one aggregate opex
 *    number; dumping it into a single arbitrary line item would misrepresent
 *    the deal's actual expense structure, which conflicts with this app's
 *    "never silently mis-populate financial inputs" principle.
 *  - dueDiligenceCosts, acquisitionFeePct, inPlaceNoi (acquisition mode) —
 *    not modeled; no dedicated quick-screen input for either.
 *  - unit/SF count — there's no generic "quantity" field in the schema. It
 *    only exists inside property-type-specific sections (unitMix table,
 *    rentableSf, homeCount), which are gated on propertyType — which, per
 *    above, the quick screen doesn't set.
 *  - amortYears, loanTermYears, ioMonths, originationFeePct, dscrConstraint,
 *    debtYieldConstraint — the quick screen's interest-only approximation has
 *    no amortization schedule, loan term, fees, or sizing-constraint concepts.
 *  - equity_structure.* (lpSplitPct, gpSplitPct, preferredReturnPct,
 *    waterfallTiers) — no promote/waterfall is modeled.
 *  - growth assumptions, holdPeriodYears, costOfSalePct — the quick screen is
 *    a single stabilized-year snapshot; no multi-year growth or hold period.
 *  - creditLossPct, otherIncome — not modeled separately from the NOI margin.
 */
export function mapQuickScreenToDealInputs(
  inputs: QuickScreenInputs,
  results: QuickScreenResults,
): Record<string, unknown> {
  const vacancyPct = inputs.useDetailedNoi ? inputs.vacancyPct : DEFAULT_IMPLIED_VACANCY_PCT
  const isAcquisition = inputs.dealMode === 'acquisition'

  const costBasisFields = isAcquisition
    ? {
        // Acquisition Details
        purchasePrice: results.purchasePrice,
        closingCostsPct: inputs.closingCostsPct,
        dayOneCapex: results.renoBudget,
        stabilizedNoi: results.stabilizedNoi, // informational cross-check in the native engine
      }
    : {
        // Development Details
        landCost: inputs.landCost,
        hardCosts: results.hardCosts,
        hardCostsPsf: inputs.hardCostPerUnit,
        softCosts: results.softCosts,
        contingencyPct: inputs.contingencyPct,
      }

  return {
    dealType: inputs.dealMode,
    ...costBasisFields,
    // Exit Assumptions
    exitCapRatePct: inputs.exitCapRatePct,
    // Operating Income
    grossPotentialRent: results.grossPotentialRent,
    vacancyPct,
    // Financing
    ltvOrLtc: inputs.ltcPct,
    interestRate: inputs.constructionInterestRatePct,
    totalCostBasis: results.totalCost,
    loanAmount: results.loanAmount,
    // Equity Structure
    totalEquity: results.equityRequired,
  }
}

// ---------------------------------------------------------------------------
// Inline sensitivity mini-grid: rent (rows) x exit cap (cols), 5x5, center =
// current inputs. Reuses computeQuickScreen per cell — no separate calc engine.
// ---------------------------------------------------------------------------

export type SensitivityGridMetric = 'yieldOnCost' | 'spread'

export interface SensitivityGridCell {
  rentDeltaPct: number
  exitCapDeltaBps: number
  value: number
  tier: FeasibilityTier
  isCenter: boolean
}

const SENSITIVITY_RENT_DELTAS_PCT = [-0.1, -0.05, 0, 0.05, 0.1]
const SENSITIVITY_EXIT_CAP_DELTAS_BPS = [-50, -25, 0, 25, 50]

export function computeQuickScreenSensitivityGrid(
  inputs: QuickScreenInputs,
  metric: SensitivityGridMetric = 'spread',
  thresholds: FeasibilityThresholds = FEASIBILITY_THRESHOLDS,
): SensitivityGridCell[][] {
  return SENSITIVITY_RENT_DELTAS_PCT.map((rentDelta) =>
    SENSITIVITY_EXIT_CAP_DELTAS_BPS.map((capDeltaBps) => {
      const scenarioInputs: QuickScreenInputs = {
        ...inputs,
        rent: inputs.rent * (1 + rentDelta),
        exitCapRatePct: inputs.exitCapRatePct + capDeltaBps / 10000,
      }
      const result = computeQuickScreen(scenarioInputs)
      const value = metric === 'yieldOnCost' ? result.yieldOnCost : result.capRateSpreadBps / 10000
      return {
        rentDeltaPct: rentDelta,
        exitCapDeltaBps: capDeltaBps,
        value,
        tier: classifyFeasibility(result.capRateSpreadBps, thresholds),
        isCenter: rentDelta === 0 && capDeltaBps === 0,
      }
    }),
  )
}

// ---------------------------------------------------------------------------
// URL query-string persistence (debounced sync lives in the component/App).
// ---------------------------------------------------------------------------

const QUICK_SCREEN_NUMERIC_KEYS = [
  'quantity',
  'landCost',
  'hardCostPerUnit',
  'softCostPct',
  'contingencyPct',
  'purchasePricePerUnit',
  'closingCostsPct',
  'renoBudgetPerUnit',
  'rent',
  'noiMarginPct',
  'exitCapRatePct',
  'ltcPct',
  'constructionInterestRatePct',
  'vacancyPct',
  'opexRatioPct',
] as const satisfies readonly (keyof QuickScreenInputs)[]

export function serializeQuickScreenInputs(inputs: QuickScreenInputs): URLSearchParams {
  const params = new URLSearchParams()
  params.set('dealMode', inputs.dealMode)
  params.set('sizeMode', inputs.sizeMode)
  params.set('detail', inputs.useDetailedNoi ? '1' : '0')
  for (const key of QUICK_SCREEN_NUMERIC_KEYS) {
    params.set(key, String(inputs[key]))
  }
  return params
}

export function parseQuickScreenInputs(params: URLSearchParams): QuickScreenInputs | null {
  const hasAny = QUICK_SCREEN_NUMERIC_KEYS.some((key) => params.has(key))
  if (!hasAny) return null

  // A URL saved before dealMode/acquisition fields existed has none of them —
  // spreading QUICK_SCREEN_DEFAULTS first means it silently reproduces the
  // original development-only behavior instead of ending up with `undefined`s.
  const result: QuickScreenInputs = { ...QUICK_SCREEN_DEFAULTS }
  const dealMode = params.get('dealMode')
  if (dealMode === 'development' || dealMode === 'acquisition') result.dealMode = dealMode
  const sizeMode = params.get('sizeMode')
  if (sizeMode === 'units' || sizeMode === 'sf') result.sizeMode = sizeMode
  result.useDetailedNoi = params.get('detail') === '1'

  const numericResult = result as unknown as Record<string, number>
  for (const key of QUICK_SCREEN_NUMERIC_KEYS) {
    const raw = params.get(key)
    if (raw === null) continue
    const num = Number(raw)
    if (Number.isFinite(num)) numericResult[key] = num
  }
  return result
}
