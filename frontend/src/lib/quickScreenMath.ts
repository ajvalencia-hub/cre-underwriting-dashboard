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
  developerFeePct: number // fraction, of (hard + soft + contingency) — the engine's base
  constructionMonths: number // build period; drives the capitalized-interest estimate
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
  developerFee: number
  /** Estimated construction interest, capitalized into cost (see below). */
  financingCost: number
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

/** Average share of the construction loan outstanding over the build, for
 *  the capitalized-interest estimate. Calibrated to the engine's equity-first
 *  S-curve draws (0.38–0.41 for 12–24 month builds at 60% LTC) rather than
 *  the 0.5 rule of thumb, so the napkin lands near Compute. */
export const QUICK_SCREEN_AVG_DRAW_FACTOR = 0.4

/** Capitalized interest as a fraction of total cost:
 *  interest = (LTC x TDC) x rate x (months / 12) x avg draw. */
function financingShareOfCost(inputs: QuickScreenInputs): number {
  const share =
    inputs.ltcPct * inputs.constructionInterestRatePct * (Math.max(0, inputs.constructionMonths) / 12) *
    QUICK_SCREEN_AVG_DRAW_FACTOR
  return Math.min(share, 0.5) // guard: a nonsensical rate/term can't blow up the total
}

export function computeQuickScreen(inputs: QuickScreenInputs): QuickScreenResults {
  const hardCosts = inputs.quantity * inputs.hardCostPerUnit
  const softCosts = hardCosts * inputs.softCostPct
  const contingency = (hardCosts + softCosts) * inputs.contingencyPct
  const developerFee = (hardCosts + softCosts + contingency) * inputs.developerFeePct
  // Interest is part of the cost the loan (a share of cost) funds — solve
  // TDC = costs + TDC x financingShare in closed form. Leaving the developer
  // fee and financing out used to make the napkin's yield on cost read
  // higher than Compute's for the same deal.
  const costsExFinancing = inputs.landCost + hardCosts + softCosts + contingency + developerFee
  const totalDevelopmentCost = costsExFinancing / (1 - financingShareOfCost(inputs))
  const financingCost = totalDevelopmentCost - costsExFinancing

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
    developerFee,
    financingCost,
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
  developerFeePct: 0.04,
  constructionMonths: 18,
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
  developerFeePct: { min: 0, max: 0.1, step: 0.005 },
  constructionMonths: { min: 0, max: 96, step: 1 },
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
 * then invert TDC = (land + hard*m*(1+devFee)) / (1 - financingShare), with
 * m = (1+softCostPct)*(1+contingencyPct), for hard cost:
 *   hardCostPerUnit = (TDC_target*(1-financingShare) - land) / (m*(1+devFee)*quantity)
 */
export function solveHardCostForSpread(inputs: QuickScreenInputs, targetBps: number): number | null {
  const targetSpreadFraction = targetBps / 10000
  const results = computeQuickScreen(inputs)
  const costMultiplier =
    (1 + inputs.softCostPct) * (1 + inputs.contingencyPct) * (1 + inputs.developerFeePct)
  if (results.stabilizedNoi <= 0 || costMultiplier <= 0 || inputs.quantity <= 0) return null

  const tdcTarget = results.stabilizedNoi / (inputs.exitCapRatePct + targetSpreadFraction)
  const requiredHardCosts =
    (tdcTarget * (1 - financingShareOfCost(inputs)) - inputs.landCost) / costMultiplier
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
    // Only a per-SF figure belongs in the PSF field — in units mode
    // hardCostPerUnit is $/unit and writing it here would be a silent
    // mis-population (the total in `hardCosts` is what the engine reads).
    ...(inputs.sizeMode === 'sf' ? { hardCostsPsf: inputs.hardCostPerUnit } : {}),
    softCosts: results.softCosts,
    contingencyPct: inputs.contingencyPct,
    developerFeePct: inputs.developerFeePct,
    constructionMonths: inputs.constructionMonths,
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
// Acquisition quick screen: the acquisition-side back-of-napkin (the module
// above is development-shaped: land + hard cost + construction loan). Same
// philosophy — pure math, components only render. Verdict is cash-on-cash +
// DSCR based (the acquisition napkin test), not yield-on-cost spread.
// ---------------------------------------------------------------------------

export interface AcquisitionQuickScreenInputs {
  purchasePrice: number
  closingCostsPct: number // fraction of price, added to the equity basis
  quantity: number // # units
  rent: number // $/unit/month
  noiMarginPct: number // fraction of GPR retained as NOI
  exitCapRatePct: number // fraction — reversion context for the cap spread
  ltvPct: number // fraction of PRICE (standard sizing basis), 0 = all cash
  interestRatePct: number // fraction
  amortYears: number // 0 = interest-only
}

export interface AcquisitionQuickScreenResults {
  totalBasis: number
  grossPotentialRent: number
  stabilizedNoi: number
  goingInCapRate: number
  capRateSpreadBps: number // going-in over exit — positive = buying above the exit cap
  pricePerUnit: number
  loanAmount: number
  equityRequired: number
  loanConstant: number | null
  annualDebtService: number
  leveredCashFlow: number
  cashOnCashPct: number | null
  minDscr: number | null
  debtYield: number | null
  breakEvenRatio: number
  feasibility: FeasibilityTier
}

/** Acquisition verdict thresholds [documented in DECISIONS.md]: cash-on-cash
 *  AND DSCR must both clear a tier. All-cash deals have no DSCR — the DSCR
 *  leg is vacuously satisfied and cash-on-cash (= unlevered yield) decides. */
export const ACQUISITION_FEASIBILITY = {
  strong: { cashOnCash: 0.06, dscr: 1.25 },
  marginal: { cashOnCash: 0.04, dscr: 1.15 },
}

export function classifyAcquisitionFeasibility(
  cashOnCash: number | null,
  dscr: number | null,
): FeasibilityTier {
  const coc = cashOnCash ?? -Infinity
  const meets = (tier: { cashOnCash: number; dscr: number }) =>
    coc >= tier.cashOnCash && (dscr === null || dscr >= tier.dscr)
  if (meets(ACQUISITION_FEASIBILITY.strong)) return 'strong'
  if (meets(ACQUISITION_FEASIBILITY.marginal)) return 'marginal'
  return 'weak'
}

/** Level-payment mortgage constant (annual debt service per $ of loan);
 *  amortYears 0 collapses to the rate (interest-only). */
export function annualLoanConstant(ratePct: number, amortYears: number): number {
  if (amortYears <= 0) return ratePct
  const r = ratePct / 12
  const n = Math.round(amortYears * 12)
  if (r === 0) return 12 / n
  return (12 * r) / (1 - (1 + r) ** -n)
}

export function computeAcquisitionQuickScreen(
  inputs: AcquisitionQuickScreenInputs,
): AcquisitionQuickScreenResults {
  const totalBasis = inputs.purchasePrice * (1 + inputs.closingCostsPct)
  const grossPotentialRent = inputs.quantity * inputs.rent * 12
  const stabilizedNoi = grossPotentialRent * inputs.noiMarginPct
  const goingInCapRate = inputs.purchasePrice > 0 ? stabilizedNoi / inputs.purchasePrice : 0
  const capRateSpreadBps = (goingInCapRate - inputs.exitCapRatePct) * 10000
  const pricePerUnit = inputs.quantity > 0 ? inputs.purchasePrice / inputs.quantity : 0

  const loanAmount = inputs.purchasePrice * inputs.ltvPct
  const equityRequired = totalBasis - loanAmount
  const loanConstant =
    loanAmount > 0 ? annualLoanConstant(inputs.interestRatePct, inputs.amortYears) : null
  const annualDebtService = loanAmount > 0 && loanConstant !== null ? loanAmount * loanConstant : 0
  const leveredCashFlow = stabilizedNoi - annualDebtService
  const cashOnCashPct = equityRequired > 0 ? leveredCashFlow / equityRequired : null
  const minDscr = annualDebtService > 0 ? stabilizedNoi / annualDebtService : null
  const debtYield = loanAmount > 0 ? stabilizedNoi / loanAmount : null
  const breakEvenRatio =
    grossPotentialRent > 0
      ? (grossPotentialRent - stabilizedNoi + annualDebtService) / grossPotentialRent
      : 0

  return {
    totalBasis,
    grossPotentialRent,
    stabilizedNoi,
    goingInCapRate,
    capRateSpreadBps,
    pricePerUnit,
    loanAmount,
    equityRequired,
    loanConstant,
    annualDebtService,
    leveredCashFlow,
    cashOnCashPct,
    minDscr,
    debtYield,
    breakEvenRatio,
    feasibility: classifyAcquisitionFeasibility(cashOnCashPct, minDscr),
  }
}

export const ACQUISITION_QUICK_SCREEN_DEFAULTS: AcquisitionQuickScreenInputs = {
  purchasePrice: 10_000_000,
  closingCostsPct: 0.02,
  quantity: 60,
  rent: 1_600,
  noiMarginPct: 0.6,
  exitCapRatePct: 0.055,
  ltvPct: 0.6,
  interestRatePct: 0.065,
  amortYears: 30,
}

/** "Send to Deal Inputs" for the acquisition screen — same single-mapping
 *  principle as the development version above; nothing guessed, the implied
 *  5% vacancy mirrors the NOI-margin decomposition. */
export function mapAcquisitionQuickScreenToDealInputs(
  inputs: AcquisitionQuickScreenInputs,
  results: AcquisitionQuickScreenResults,
): Record<string, unknown> {
  return {
    dealType: 'acquisition',
    // Acquisition Details
    purchasePrice: inputs.purchasePrice,
    closingCostsPct: inputs.closingCostsPct,
    inPlaceNoi: results.stabilizedNoi,
    // Operating Income
    grossPotentialRent: results.grossPotentialRent,
    vacancyPct: DEFAULT_IMPLIED_VACANCY_PCT,
    // Exit Assumptions
    exitCapRatePct: inputs.exitCapRatePct,
    // Financing
    ltvOrLtc: inputs.ltvPct,
    loanAmount: results.loanAmount,
    interestRate: inputs.interestRatePct,
    amortYears: inputs.amortYears,
    totalCostBasis: results.totalBasis,
    // Equity Structure
    totalEquity: results.equityRequired,
  }
}

// ---------------------------------------------------------------------------
// Acquisition solve-fors: closed-form "what would it take" for a target
// tier. Both constraints of the verdict (cash-on-cash AND DSCR) are solved
// and combined — hitting the CoC target at a price the DSCR still fails
// would not flip the tier.
// ---------------------------------------------------------------------------

/**
 * Max price for a target cash-on-cash t AND DSCR d, with NOI fixed
 * (price doesn't change rents):
 *   CoC:  t = (NOI − p·ltv·k) / (p·(1+cc) − p·ltv)
 *         → p·(t·(1+cc−ltv) + ltv·k) = NOI
 *         → p_CoC = NOI / (t·(1+cc−ltv) + ltv·k)
 *   DSCR: d ≤ NOI / (p·ltv·k) → p_DSCR = NOI / (d·ltv·k)
 *   answer = min(p_CoC, p_DSCR); all-cash (ltv=0) → p = NOI / (t·(1+cc)).
 */
export function solveAcquisitionPriceForTier(
  inputs: AcquisitionQuickScreenInputs,
  targetCashOnCash: number,
  targetDscr: number,
): number | null {
  const results = computeAcquisitionQuickScreen(inputs)
  const noi = results.stabilizedNoi
  if (noi <= 0) return null
  const cc = inputs.closingCostsPct
  const ltv = inputs.ltvPct
  const k = annualLoanConstant(inputs.interestRatePct, inputs.amortYears)
  const cocDenominator = targetCashOnCash * (1 + cc - ltv) + ltv * k
  if (cocDenominator <= 0) return null
  const priceForCoc = noi / cocDenominator
  if (ltv <= 0 || k <= 0) return priceForCoc
  const priceForDscr = noi / (targetDscr * ltv * k)
  return Math.min(priceForCoc, priceForDscr)
}

/**
 * Required rent for a target tier with price/terms fixed. NOI is linear in
 * rent (NOI = 12·q·rent·margin), so solve the binding constraint:
 *   CoC:  NOI ≥ t·equity + DS
 *   DSCR: NOI ≥ d·DS
 *   NOI_target = max of the two → rent = NOI_target / (12·q·margin).
 */
export function solveAcquisitionRentForTier(
  inputs: AcquisitionQuickScreenInputs,
  targetCashOnCash: number,
  targetDscr: number,
): number | null {
  if (inputs.quantity <= 0 || inputs.noiMarginPct <= 0) return null
  const results = computeAcquisitionQuickScreen(inputs)
  const noiForCoc = targetCashOnCash * results.equityRequired + results.annualDebtService
  const noiForDscr = results.annualDebtService > 0 ? targetDscr * results.annualDebtService : 0
  const noiTarget = Math.max(noiForCoc, noiForDscr)
  if (noiTarget <= 0) return null
  return noiTarget / (12 * inputs.quantity * inputs.noiMarginPct)
}

// ---------------------------------------------------------------------------
// Acquisition sidebar wiring + URL persistence (share/reload parity with the
// development screen). Acquisition params are `acq_`-prefixed so existing
// shared development links keep their meaning; the active napkin rides in a
// `screen` param.
// ---------------------------------------------------------------------------

export function mapAcquisitionQuickScreenToOutputMetrics(
  results: AcquisitionQuickScreenResults,
  inputs: AcquisitionQuickScreenInputs,
): Record<string, number> {
  const out: Record<string, number> = {}
  const set = (id: string, value: number | null) => {
    if (value !== null && Number.isFinite(value)) out[id] = value
  }
  set('goingInCapRate', results.goingInCapRate)
  // Reversion at the exit cap on today's NOI — the napkin's single-year view.
  set('terminalValue', inputs.exitCapRatePct > 0 ? results.stabilizedNoi / inputs.exitCapRatePct : null)
  set('ltv', inputs.ltvPct > 0 ? inputs.ltvPct : null)
  set('debtYield', results.debtYield)
  set('loanConstant', results.loanConstant)
  set('breakEvenRatio', results.breakEvenRatio)
  set('minDscr', results.minDscr)
  set('avgDscr', results.minDscr) // single stabilized year — identical
  set('stabilizedCashOnCash', results.cashOnCashPct)
  return out
}

const ACQ_NUMERIC_KEYS = [
  'purchasePrice', 'closingCostsPct', 'quantity', 'rent', 'noiMarginPct',
  'exitCapRatePct', 'ltvPct', 'interestRatePct', 'amortYears',
] as const satisfies readonly (keyof AcquisitionQuickScreenInputs)[]

export function serializeAcquisitionQuickScreenInputs(
  inputs: AcquisitionQuickScreenInputs,
  params: URLSearchParams = new URLSearchParams(),
): URLSearchParams {
  for (const key of ACQ_NUMERIC_KEYS) params.set(`acq_${key}`, String(inputs[key]))
  return params
}

export function parseAcquisitionQuickScreenInputs(
  params: URLSearchParams,
): AcquisitionQuickScreenInputs | null {
  const hasAny = ACQ_NUMERIC_KEYS.some((key) => params.has(`acq_${key}`))
  if (!hasAny) return null
  const result = { ...ACQUISITION_QUICK_SCREEN_DEFAULTS }
  const numeric = result as unknown as Record<string, number>
  for (const key of ACQ_NUMERIC_KEYS) {
    const raw = params.get(`acq_${key}`)
    if (raw === null) continue
    const num = Number(raw)
    if (Number.isFinite(num)) numeric[key] = num
  }
  return result
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
  'developerFeePct',
  'constructionMonths',
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
