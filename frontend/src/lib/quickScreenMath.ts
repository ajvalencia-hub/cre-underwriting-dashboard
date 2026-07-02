// Pure calculation module for the Back-of-Napkin Quick Screen. Every formula the
// panel and the summary sidebar display lives here — components only format and
// render these results, never recompute them.

export type SizeMode = 'units' | 'sf'
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
  sizeMode: SizeMode
  quantity: number // # units, or total SF
  landCost: number
  hardCostPerUnit: number // $ per unit or per SF, depending on sizeMode
  softCostPct: number // fraction, e.g. 0.20 = 20% of hard cost
  contingencyPct: number // fraction, of (hard + soft)
  rent: number // $/unit/month if sizeMode === 'units', else $/SF/year
  noiMarginPct: number // fraction of gross potential rent retained as NOI (simple mode)
  exitCapRatePct: number // fraction
  ltcPct: number // fraction, 0 disables leverage output
  constructionInterestRatePct: number // fraction, interest-only approximation
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
  hardCosts: number
  softCosts: number
  contingency: number
  totalDevelopmentCost: number

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
  const hardCosts = inputs.quantity * inputs.hardCostPerUnit
  const softCosts = hardCosts * inputs.softCostPct
  const contingency = (hardCosts + softCosts) * inputs.contingencyPct
  const totalDevelopmentCost = inputs.landCost + hardCosts + softCosts + contingency

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

  const profit = stabilizedValue - totalDevelopmentCost
  const profitMarginPct = totalDevelopmentCost > 0 ? profit / totalDevelopmentCost : 0

  const yieldOnCost = totalDevelopmentCost > 0 ? stabilizedNoi / totalDevelopmentCost : 0
  // No separate acquisition price exists for a ground-up deal — the cost basis
  // doubles as the "going-in" basis, so going-in cap rate collapses to yield on cost.
  const goingInCapRate = yieldOnCost
  const capRateSpreadBps = (yieldOnCost - inputs.exitCapRatePct) * 10000
  const feasibility = classifyFeasibility(capRateSpreadBps)

  const loanAmount = totalDevelopmentCost * inputs.ltcPct
  const equityRequired = totalDevelopmentCost - loanAmount
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
    totalDevelopmentCost,
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
  sizeMode: 'units',
  quantity: 100,
  landCost: 3_000_000,
  hardCostPerUnit: 180_000,
  softCostPct: 0.2,
  contingencyPct: 0.05,
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

  const requiredNoi = results.totalDevelopmentCost * (inputs.exitCapRatePct + targetSpreadFraction)
  const requiredGpr = requiredNoi / results.effectiveNoiMarginPct
  return requiredGpr / (inputs.quantity * annualFactor)
}

/**
 * Hard cost/unit: NOI doesn't depend on hard cost, so solve for the TDC that
 * produces the target yield on cost (TDC_target = NOI / (exitCap + targetSpread)),
 * then invert TDC = land + hard*(1+softCostPct)*(1+contingencyPct) for hard cost:
 *   hardCostPerUnit = (TDC_target - land) / ((1+softCostPct)*(1+contingencyPct)*quantity)
 */
export function solveHardCostForSpread(inputs: QuickScreenInputs, targetBps: number): number | null {
  const targetSpreadFraction = targetBps / 10000
  const results = computeQuickScreen(inputs)
  const costMultiplier = (1 + inputs.softCostPct) * (1 + inputs.contingencyPct)
  if (results.stabilizedNoi <= 0 || costMultiplier <= 0 || inputs.quantity <= 0) return null

  const tdcTarget = results.stabilizedNoi / (inputs.exitCapRatePct + targetSpreadFraction)
  const requiredHardCosts = (tdcTarget - inputs.landCost) / costMultiplier
  return requiredHardCosts > 0 ? requiredHardCosts / inputs.quantity : null
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
 * "Send to Deal Inputs" and "Save as Scenario".
 *
 * NOT mapped, and why:
 *  - propertyType / mixedUseComponents — sizeMode ('units' vs 'sf') doesn't
 *    reliably imply a property type (SF-denominated could be office, retail,
 *    industrial, etc.), so guessing would be worse than leaving it blank.
 *  - operating_expenses.* (realEstateTaxes, insurance, utilities,
 *    repairsMaintenance, payroll, generalAdmin, managementFeePct,
 *    replacementReserves) — the quick screen only produces one aggregate opex
 *    number; dumping it into a single arbitrary line item would misrepresent
 *    the deal's actual expense structure, which conflicts with this app's
 *    "never silently mis-populate financial inputs" principle.
 *  - acquisition_specific.* (purchasePrice, closingCostsPct, dueDiligenceCosts,
 *    acquisitionFeePct, dayOneCapex, inPlaceNoi, stabilizedNoi) — that section
 *    is gated on dealType === 'acquisition'; irrelevant since this always maps
 *    to dealType === 'development'.
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
  return {
    dealType: 'development',
    // Development Details
    landCost: inputs.landCost,
    hardCosts: results.hardCosts,
    hardCostsPsf: inputs.hardCostPerUnit,
    softCosts: results.softCosts,
    contingencyPct: inputs.contingencyPct,
    // Exit Assumptions
    exitCapRatePct: inputs.exitCapRatePct,
    // Operating Income
    grossPotentialRent: results.grossPotentialRent,
    vacancyPct,
    // Financing
    ltvOrLtc: inputs.ltcPct,
    interestRate: inputs.constructionInterestRatePct,
    totalCostBasis: results.totalDevelopmentCost,
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

  const result: QuickScreenInputs = { ...QUICK_SCREEN_DEFAULTS }
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
