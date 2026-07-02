export type SizeMode = 'units' | 'sf'

export interface QuickScreenInputs {
  sizeMode: SizeMode
  quantity: number // # units, or total SF
  landCost: number
  hardCostPerUnit: number // $ per unit or per SF, depending on sizeMode
  softCostPct: number // fraction, e.g. 0.20 = 20% of hard cost
  contingencyPct: number // fraction, of (hard + soft)
  rent: number // $/unit/month if sizeMode === 'units', else $/SF/year
  noiMarginPct: number // fraction of gross potential rent retained as NOI
  exitCapRatePct: number // fraction
  ltcPct: number // fraction, 0 disables leverage output
  constructionInterestRatePct: number // fraction, interest-only approximation
}

export interface QuickScreenResults {
  hardCosts: number
  softCosts: number
  contingency: number
  totalDevelopmentCost: number
  grossPotentialRent: number
  stabilizedNoi: number
  stabilizedValue: number
  profit: number
  profitMarginPct: number
  yieldOnCost: number
  capRateSpreadBps: number
  feasibility: 'strong' | 'marginal' | 'weak'
  loanAmount: number
  equityRequired: number
  leveredCashFlow: number
  cashOnCashPct: number | null
}

export function computeQuickScreen(inputs: QuickScreenInputs): QuickScreenResults {
  const hardCosts = inputs.quantity * inputs.hardCostPerUnit
  const softCosts = hardCosts * inputs.softCostPct
  const contingency = (hardCosts + softCosts) * inputs.contingencyPct
  const totalDevelopmentCost = inputs.landCost + hardCosts + softCosts + contingency

  const grossPotentialRent =
    inputs.sizeMode === 'units' ? inputs.quantity * inputs.rent * 12 : inputs.quantity * inputs.rent

  const stabilizedNoi = grossPotentialRent * inputs.noiMarginPct
  const stabilizedValue = inputs.exitCapRatePct > 0 ? stabilizedNoi / inputs.exitCapRatePct : 0

  const profit = stabilizedValue - totalDevelopmentCost
  const profitMarginPct = totalDevelopmentCost > 0 ? profit / totalDevelopmentCost : 0

  const yieldOnCost = totalDevelopmentCost > 0 ? stabilizedNoi / totalDevelopmentCost : 0
  const capRateSpreadBps = (yieldOnCost - inputs.exitCapRatePct) * 10000

  let feasibility: QuickScreenResults['feasibility'] = 'weak'
  if (capRateSpreadBps >= 200) feasibility = 'strong'
  else if (capRateSpreadBps >= 100) feasibility = 'marginal'

  const loanAmount = totalDevelopmentCost * inputs.ltcPct
  const equityRequired = totalDevelopmentCost - loanAmount
  const annualDebtService = loanAmount * inputs.constructionInterestRatePct
  const leveredCashFlow = stabilizedNoi - annualDebtService
  const cashOnCashPct = equityRequired > 0 ? leveredCashFlow / equityRequired : null

  return {
    hardCosts,
    softCosts,
    contingency,
    totalDevelopmentCost,
    grossPotentialRent,
    stabilizedNoi,
    stabilizedValue,
    profit,
    profitMarginPct,
    yieldOnCost,
    capRateSpreadBps,
    feasibility,
    loanAmount,
    equityRequired,
    leveredCashFlow,
    cashOnCashPct,
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
}
