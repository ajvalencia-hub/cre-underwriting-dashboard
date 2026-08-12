import { describe, expect, it } from 'vitest'
import {
  ACQUISITION_QUICK_SCREEN_DEFAULTS,
  annualLoanConstant,
  classifyAcquisitionFeasibility,
  computeAcquisitionQuickScreen,
  computeQuickScreen,
  mapAcquisitionQuickScreenToDealInputs,
  mapQuickScreenToDealInputs,
  QUICK_SCREEN_DEFAULTS,
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
