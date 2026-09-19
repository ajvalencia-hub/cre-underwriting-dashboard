import { describe, expect, it } from 'vitest'
import {
  ACQUISITION_FEASIBILITY,
  ACQUISITION_QUICK_SCREEN_DEFAULTS,
  annualLoanConstant,
  classifyAcquisitionFeasibility,
  computeAcquisitionQuickScreen,
  computeQuickScreen,
  mapAcquisitionQuickScreenToDealInputs,
  mapAcquisitionQuickScreenToOutputMetrics,
  mapQuickScreenToDealInputs,
  parseAcquisitionQuickScreenInputs,
  QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_OPEX_NOTE,
  serializeAcquisitionQuickScreenInputs,
  solveAcquisitionPriceForTier,
  solveAcquisitionRentForTier,
  type AcquisitionQuickScreenInputs,
} from './quickScreenMath'

// Hand fixture: $1.0M price + 2% closing, 10 units x $1,000/mo, 60% NOI
// margin, 6% exit cap, 60% LTV at 6% / 30yr.
//   GPR 120,000 -> NOI 72,000 -> going-in cap 7.2% -> +120bps vs exit.
//   Loan 600,000; equity 1,020,000 - 600,000 = 420,000.
//   Constant = 12·PMT(0.5%, 360, 1) = 7.1946% -> DS 43,168.
//   CoC = (72,000 - 43,168)/420,000 = 6.865%; DSCR = 1.668 -> strong.
const BASE: AcquisitionQuickScreenInputs = {
  purchasePrice: 1_000_000,
  closingCostsPct: 0.02,
  quantity: 10,
  rent: 1_000,
  noiMarginPct: 0.6,
  exitCapRatePct: 0.06,
  ltvPct: 0.6,
  interestRatePct: 0.06,
  amortYears: 30,
}

describe('computeAcquisitionQuickScreen', () => {
  it('reproduces the hand numbers', () => {
    const r = computeAcquisitionQuickScreen(BASE)
    expect(r.totalBasis).toBeCloseTo(1_020_000, 2)
    expect(r.grossPotentialRent).toBeCloseTo(120_000, 2)
    expect(r.stabilizedNoi).toBeCloseTo(72_000, 2)
    expect(r.goingInCapRate).toBeCloseTo(0.072, 8)
    expect(r.capRateSpreadBps).toBeCloseTo(120, 6)
    expect(r.pricePerUnit).toBeCloseTo(100_000, 2)
    expect(r.loanAmount).toBeCloseTo(600_000, 2)
    expect(r.equityRequired).toBeCloseTo(420_000, 2)
    expect(r.loanConstant).toBeCloseTo(0.0719461, 5)
    expect(r.annualDebtService).toBeCloseTo(600_000 * 0.0719461, 0)
    expect(r.cashOnCashPct).toBeCloseTo((72_000 - 600_000 * 0.0719461) / 420_000, 5)
    expect(r.minDscr).toBeCloseTo(72_000 / (600_000 * 0.0719461), 5)
    expect(r.debtYield).toBeCloseTo(0.12, 8)
    expect(r.feasibility).toBe('strong')
  })

  it('all-cash: no DSCR, verdict decided by cash-on-cash alone', () => {
    const r = computeAcquisitionQuickScreen({ ...BASE, ltvPct: 0 })
    expect(r.loanAmount).toBe(0)
    expect(r.minDscr).toBeNull()
    expect(r.annualDebtService).toBe(0)
    // CoC = unlevered yield on basis = 72,000 / 1,020,000 = 7.06% -> strong.
    expect(r.cashOnCashPct).toBeCloseTo(72_000 / 1_020_000, 6)
    expect(r.feasibility).toBe('strong')
  })

  it('interest-only when amortYears = 0 (constant collapses to the rate)', () => {
    const r = computeAcquisitionQuickScreen({ ...BASE, amortYears: 0 })
    expect(r.loanConstant).toBeCloseTo(0.06, 10)
    expect(r.annualDebtService).toBeCloseTo(36_000, 6)
  })
})

describe('classifyAcquisitionFeasibility', () => {
  it('needs BOTH cash-on-cash and DSCR to clear a tier', () => {
    expect(classifyAcquisitionFeasibility(0.07, 1.3)).toBe('strong')
    expect(classifyAcquisitionFeasibility(0.07, 1.2)).toBe('marginal') // DSCR misses strong
    expect(classifyAcquisitionFeasibility(0.05, 1.5)).toBe('marginal') // CoC misses strong
    expect(classifyAcquisitionFeasibility(0.03, 2.0)).toBe('weak')
    expect(classifyAcquisitionFeasibility(null, null)).toBe('weak')
    // All-cash: DSCR leg vacuously satisfied.
    expect(classifyAcquisitionFeasibility(0.065, null)).toBe('strong')
  })
})

describe('annualLoanConstant', () => {
  it('matches the mortgage formula and IO edge', () => {
    expect(annualLoanConstant(0.06, 30)).toBeCloseTo(0.0719461, 5)
    expect(annualLoanConstant(0.06, 0)).toBe(0.06)
    expect(annualLoanConstant(0, 30)).toBeCloseTo(12 / 360, 10)
  })
})

describe('mapAcquisitionQuickScreenToDealInputs', () => {
  it('sets dealType acquisition and the reviewed fields, nothing guessed', () => {
    const results = computeAcquisitionQuickScreen(BASE)
    const mapped = mapAcquisitionQuickScreenToDealInputs(BASE, results)
    expect(mapped.dealType).toBe('acquisition')
    expect(mapped.purchasePrice).toBe(1_000_000)
    expect(mapped.inPlaceNoi).toBeCloseTo(72_000, 2)
    expect(mapped.loanAmount).toBeCloseTo(600_000, 2)
    expect(mapped.amortYears).toBe(30)
    expect(mapped.totalEquity).toBeCloseTo(420_000, 2)
    // Never touches development fields.
    expect(mapped).not.toHaveProperty('landCost')
    expect(mapped).not.toHaveProperty('hardCosts')
  })

  it('defaults are self-consistent', () => {
    const r = computeAcquisitionQuickScreen(ACQUISITION_QUICK_SCREEN_DEFAULTS)
    expect(r.stabilizedNoi).toBeGreaterThan(0)
    expect(r.feasibility).toMatch(/strong|marginal|weak/)
  })
})

describe('solve-fors', () => {
  it('solved price reproduces the target tier exactly (both legs)', () => {
    // Start from a WEAK deal: high price relative to NOI.
    const weak = { ...BASE, purchasePrice: 1_600_000 }
    expect(computeAcquisitionQuickScreen(weak).feasibility).toBe('weak')
    const target = ACQUISITION_FEASIBILITY.marginal
    const price = solveAcquisitionPriceForTier(weak, target.cashOnCash, target.dscr)!
    // At the solved price the deal sits exactly on the marginal boundary.
    const at = computeAcquisitionQuickScreen({ ...weak, purchasePrice: price })
    expect(
      Math.min(
        (at.cashOnCashPct ?? 0) - target.cashOnCash,
        (at.minDscr ?? Infinity) - target.dscr,
      ),
    ).toBeCloseTo(0, 6) // the binding constraint lands on its threshold
    expect(at.feasibility).toBe('marginal')
  })

  it('solved rent reproduces the target tier with price fixed', () => {
    const weak = { ...BASE, purchasePrice: 1_600_000 }
    const target = ACQUISITION_FEASIBILITY.marginal
    const rent = solveAcquisitionRentForTier(weak, target.cashOnCash, target.dscr)!
    const at = computeAcquisitionQuickScreen({ ...weak, rent })
    expect(
      Math.min(
        (at.cashOnCashPct ?? 0) - target.cashOnCash,
        (at.minDscr ?? Infinity) - target.dscr,
      ),
    ).toBeCloseTo(0, 6)
    expect(at.feasibility).toBe('marginal')
  })

  it('all-cash price solve uses the CoC leg alone', () => {
    const cash = { ...BASE, ltvPct: 0, purchasePrice: 2_000_000 }
    const price = solveAcquisitionPriceForTier(cash, 0.06, 1.25)!
    // p = NOI / (t·(1+cc)): 72,000 / (0.06 · 1.02) = 1,176,470.6
    expect(price).toBeCloseTo(72_000 / (0.06 * 1.02), 2)
  })
})

describe('sidebar mapping + URL round-trip', () => {
  it('maps the derivable output ids only', () => {
    const r = computeAcquisitionQuickScreen(BASE)
    const out = mapAcquisitionQuickScreenToOutputMetrics(r, BASE)
    expect(out.goingInCapRate).toBeCloseTo(0.072, 8)
    expect(out.terminalValue).toBeCloseTo(72_000 / 0.06, 2)
    expect(out.minDscr).toBe(out.avgDscr) // single-year napkin
    expect(out.stabilizedCashOnCash).toBeCloseTo(r.cashOnCashPct!, 10)
    expect(out).not.toHaveProperty('leveredIrr') // full-model only
  })

  it('serialize/parse round-trips with the acq_ prefix', () => {
    const params = serializeAcquisitionQuickScreenInputs(BASE)
    expect(params.get('acq_purchasePrice')).toBe('1000000')
    expect(params.get('purchasePrice')).toBeNull() // never collides with dev keys
    const parsed = parseAcquisitionQuickScreenInputs(params)!
    expect(parsed).toEqual(BASE)
    // No acq_ params at all -> null (dev-only links unchanged).
    expect(parseAcquisitionQuickScreenInputs(new URLSearchParams('rent=1800'))).toBeNull()
    // Junk values fall back to defaults per key.
    const junk = new URLSearchParams('acq_purchasePrice=abc&acq_rent=1234')
    const fromJunk = parseAcquisitionQuickScreenInputs(junk)!
    expect(fromJunk.purchasePrice).toBe(ACQUISITION_QUICK_SCREEN_DEFAULTS.purchasePrice)
    expect(fromJunk.rent).toBe(1234)
  })
})

describe('development mapping hardCostsPsf fix', () => {
  it('omits hardCostsPsf in units mode (a $/unit figure is not a PSF)', () => {
    const inputs = { ...QUICK_SCREEN_DEFAULTS, sizeMode: 'units' as const }
    const mapped = mapQuickScreenToDealInputs(inputs, computeQuickScreen(inputs))
    expect(mapped).not.toHaveProperty('hardCostsPsf')
    expect(mapped.hardCosts).toBeGreaterThan(0) // the total still maps
  })

  it('includes hardCostsPsf in sf mode', () => {
    const inputs = { ...QUICK_SCREEN_DEFAULTS, sizeMode: 'sf' as const, hardCostPerUnit: 200 }
    const mapped = mapQuickScreenToDealInputs(inputs, computeQuickScreen(inputs))
    expect(mapped.hardCostsPsf).toBe(200)
  })
})

describe('Send to Deal Inputs carries the napkin expenses', () => {
  const row = (mapped: Record<string, unknown>) => (mapped.opexLineItems as Record<string, unknown>[])[0]

  it('development: one annual "other" row equal to the napkin opex', () => {
    const results = computeQuickScreen(QUICK_SCREEN_DEFAULTS)
    const mapped = mapQuickScreenToDealInputs(QUICK_SCREEN_DEFAULTS, results)
    expect(mapped.opexLineItems).toHaveLength(1)
    expect(row(mapped)).toMatchObject({ category: 'other', basis: 'annual_total', note: QUICK_SCREEN_OPEX_NOTE })
    expect(row(mapped).amount).toBeCloseTo(results.operatingExpenses, 6)
    expect(mapped.creditLossPct).toBe(0)
  })

  it('acquisition: the margin implied opex at the implied 5% vacancy', () => {
    const results = computeAcquisitionQuickScreen(BASE)
    const mapped = mapAcquisitionQuickScreenToDealInputs(BASE, results)
    const egi = results.grossPotentialRent * 0.95
    expect(egi - (row(mapped).amount as number)).toBeCloseTo(results.stabilizedNoi, 6)
    expect(mapped.creditLossPct).toBe(0)
  })
})
