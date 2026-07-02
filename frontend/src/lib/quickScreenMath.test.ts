import { describe, expect, it } from 'vitest'
import {
  FEASIBILITY_THRESHOLDS,
  QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS,
  classifyFeasibility,
  computeQuickScreen,
  computeQuickScreenSensitivityGrid,
  deriveOpexRatioFromMargin,
  mapQuickScreenToOutputMetrics,
  parseQuickScreenInputs,
  serializeQuickScreenInputs,
  solveExitCapForSpread,
  solveHardCostForSpread,
  solveRentForSpread,
  type QuickScreenInputs,
} from './quickScreenMath'

const BASE: QuickScreenInputs = {
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
  vacancyPct: 0.05,
  opexRatioPct: deriveOpexRatioFromMargin(0.6, 0.05),
}

describe('TDC composition', () => {
  it('computes hard, soft, contingency, and total development cost', () => {
    const r = computeQuickScreen(BASE)
    expect(r.hardCosts).toBeCloseTo(100 * 180_000, 6) // 18,000,000
    expect(r.softCosts).toBeCloseTo(r.hardCosts * 0.2, 6) // 20% of hard
    expect(r.contingency).toBeCloseTo((r.hardCosts + r.softCosts) * 0.05, 6) // 5% of hard+soft
    expect(r.totalDevelopmentCost).toBeCloseTo(
      BASE.landCost + r.hardCosts + r.softCosts + r.contingency,
      6,
    )
  })
})

describe('stabilized value', () => {
  it('equals NOI / exit cap', () => {
    const r = computeQuickScreen(BASE)
    expect(r.stabilizedValue).toBeCloseTo(r.stabilizedNoi / BASE.exitCapRatePct, 6)
  })

  it('is 0 when exit cap is 0 (guarded, not Infinity)', () => {
    const r = computeQuickScreen({ ...BASE, exitCapRatePct: 0 })
    expect(r.stabilizedValue).toBe(0)
  })
})

describe('spread math and tier boundaries', () => {
  it('spread = (yield on cost - exit cap) * 10000', () => {
    const r = computeQuickScreen(BASE)
    expect(r.capRateSpreadBps).toBeCloseTo((r.yieldOnCost - BASE.exitCapRatePct) * 10000, 6)
  })

  it('classifies at the exact configured thresholds (150 / 100 bps)', () => {
    expect(classifyFeasibility(FEASIBILITY_THRESHOLDS.strong)).toBe('strong')
    expect(classifyFeasibility(FEASIBILITY_THRESHOLDS.strong - 0.01)).toBe('marginal')
    expect(classifyFeasibility(FEASIBILITY_THRESHOLDS.marginal)).toBe('marginal')
    expect(classifyFeasibility(FEASIBILITY_THRESHOLDS.marginal - 0.01)).toBe('weak')
  })

  it('honors a custom thresholds object instead of hardcoded values', () => {
    expect(classifyFeasibility(120, { strong: 100, marginal: 50 })).toBe('strong')
  })
})

describe('DSCR / debt yield / loan constant / break-even ratio', () => {
  it('computes standard leverage formulas', () => {
    const r = computeQuickScreen(BASE)
    expect(r.loanAmount).toBeCloseTo(r.totalDevelopmentCost * 0.6, 6)
    expect(r.debtYield).toBeCloseTo(r.stabilizedNoi / r.loanAmount, 6)
    expect(r.loanConstant).toBeCloseTo(BASE.constructionInterestRatePct, 6) // IO: constant == rate
    expect(r.minDscr).toBeCloseTo(r.stabilizedNoi / r.annualDebtService, 6)
    expect(r.avgDscr).toBe(r.minDscr) // identical under the single-year IO approximation
  })

  it('break-even ratio = (opex + debt service) / GPR, opex = GPR - NOI', () => {
    const r = computeQuickScreen(BASE)
    expect(r.breakEvenRatio).toBeCloseTo(
      (r.grossPotentialRent - r.stabilizedNoi + r.annualDebtService) / r.grossPotentialRent,
      6,
    )
  })

  it('matches hand-calculated fixtures with clean round numbers', () => {
    // 10 units, $100k/unit hard cost, no soft/contingency/land -> TDC = $1,000,000.
    // $1,000/mo/unit -> GPR = $120,000. 50% margin -> NOI = $60,000.
    // 50% LTC -> loan = $500,000. 8% IO rate -> debt service = $40,000.
    const fixture: QuickScreenInputs = {
      ...BASE,
      quantity: 10,
      landCost: 0,
      hardCostPerUnit: 100_000,
      softCostPct: 0,
      contingencyPct: 0,
      rent: 1_000,
      noiMarginPct: 0.5,
      exitCapRatePct: 0.06,
      ltcPct: 0.5,
      constructionInterestRatePct: 0.08,
    }
    const r = computeQuickScreen(fixture)
    expect(r.totalDevelopmentCost).toBe(1_000_000)
    expect(r.grossPotentialRent).toBe(120_000)
    expect(r.stabilizedNoi).toBe(60_000)
    expect(r.loanAmount).toBe(500_000)
    expect(r.annualDebtService).toBe(40_000)
    expect(r.debtYield).toBeCloseTo(0.12, 9) // 60,000 / 500,000
    expect(r.minDscr).toBeCloseTo(1.5, 9) // 60,000 / 40,000
    expect(r.avgDscr).toBeCloseTo(1.5, 9)
    expect(r.breakEvenRatio).toBeCloseTo(100_000 / 120_000, 9) // (120k - 60k + 40k) / 120k
  })
})

describe('all-equity edge case (LTC = 0)', () => {
  it('nulls out loan-dependent metrics but still computes cash-on-cash as unlevered', () => {
    const r = computeQuickScreen({ ...BASE, ltcPct: 0 })
    expect(r.loanAmount).toBe(0)
    expect(r.debtYield).toBeNull()
    expect(r.loanConstant).toBeNull()
    expect(r.minDscr).toBeNull()
    expect(r.equityRequired).toBeCloseTo(r.totalDevelopmentCost, 6)
    expect(r.cashOnCashPct).toBeCloseTo(r.yieldOnCost, 6)
  })

  it('hides the leverage card at the component level (ltcPct === 0), covered by not throwing here', () => {
    // Pure-module guard: computeQuickScreen must never throw for the all-equity
    // case, since QuickScreen.tsx conditionally renders the leverage card on
    // `inputs.ltcPct > 0` rather than on any computed field.
    expect(() => computeQuickScreen({ ...BASE, ltcPct: 0 })).not.toThrow()
  })
})

describe('per-SF vs per-unit parity', () => {
  it('produces identical totals for equivalent unit- and SF-denominated inputs', () => {
    const sfPerUnit = 900
    const unitsResult = computeQuickScreen(BASE)

    const sfInputs: QuickScreenInputs = {
      ...BASE,
      sizeMode: 'sf',
      quantity: BASE.quantity * sfPerUnit,
      hardCostPerUnit: BASE.hardCostPerUnit / sfPerUnit,
      rent: (BASE.rent * 12) / sfPerUnit,
    }
    const sfResult = computeQuickScreen(sfInputs)

    expect(sfResult.hardCosts).toBeCloseTo(unitsResult.hardCosts, 6)
    expect(sfResult.grossPotentialRent).toBeCloseTo(unitsResult.grossPotentialRent, 6)
    expect(sfResult.totalDevelopmentCost).toBeCloseTo(unitsResult.totalDevelopmentCost, 6)
    expect(sfResult.stabilizedNoi).toBeCloseTo(unitsResult.stabilizedNoi, 6)
    expect(sfResult.yieldOnCost).toBeCloseTo(unitsResult.yieldOnCost, 6)
  })
})

describe('solve-for functions round-trip to a target spread', () => {
  // Start from a deliberately weak deal so all three solves are exercised.
  const weak: QuickScreenInputs = { ...BASE, rent: 1_200, exitCapRatePct: 0.065 }
  const targetBps = FEASIBILITY_THRESHOLDS.marginal

  it('solveRentForSpread hits the target spread exactly', () => {
    const solvedRent = solveRentForSpread(weak, targetBps)
    expect(solvedRent).not.toBeNull()
    const r = computeQuickScreen({ ...weak, rent: solvedRent! })
    expect(r.capRateSpreadBps).toBeCloseTo(targetBps, 4)
  })

  it('solveHardCostForSpread hits the target spread exactly', () => {
    const solvedHardCost = solveHardCostForSpread(weak, targetBps)
    expect(solvedHardCost).not.toBeNull()
    const r = computeQuickScreen({ ...weak, hardCostPerUnit: solvedHardCost! })
    expect(r.capRateSpreadBps).toBeCloseTo(targetBps, 4)
  })

  it('solveExitCapForSpread hits the target spread exactly', () => {
    const solvedExitCap = solveExitCapForSpread(weak, targetBps)
    expect(solvedExitCap).not.toBeNull()
    const r = computeQuickScreen({ ...weak, exitCapRatePct: solvedExitCap! })
    expect(r.capRateSpreadBps).toBeCloseTo(targetBps, 4)
  })

  it('round-trips to an arbitrary target, not just the marginal threshold', () => {
    const solvedExitCap = solveExitCapForSpread(weak, 250)
    expect(solvedExitCap).not.toBeNull()
    const r = computeQuickScreen({ ...weak, exitCapRatePct: solvedExitCap! })
    expect(r.capRateSpreadBps).toBeCloseTo(250, 4)
  })
})

describe('NOI detail disclosure', () => {
  it('defaults reproduce the historical 60% margin exactly', () => {
    const r = computeQuickScreen(QUICK_SCREEN_DEFAULTS)
    expect(r.effectiveNoiMarginPct).toBeCloseTo(0.6, 9)
  })

  it('detailed mode with the derived opex ratio matches simple-mode NOI exactly', () => {
    const simple = computeQuickScreen({ ...BASE, useDetailedNoi: false, noiMarginPct: 0.55 })
    const opexRatioPct = deriveOpexRatioFromMargin(0.55, 0.05)
    const detailed = computeQuickScreen({
      ...BASE,
      useDetailedNoi: true,
      vacancyPct: 0.05,
      opexRatioPct,
    })
    expect(detailed.stabilizedNoi).toBeCloseTo(simple.stabilizedNoi, 6)
    expect(detailed.effectiveNoiMarginPct).toBeCloseTo(0.55, 9)
  })
})

describe('output metric mapping', () => {
  it('only includes derivable ids, never the full-model-only ones', () => {
    const r = computeQuickScreen(BASE)
    const mapped = mapQuickScreenToOutputMetrics(r, BASE)
    for (const id of QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS) {
      expect(mapped[id]).toBeUndefined()
    }
    expect(mapped.yieldOnCost).toBeCloseTo(r.yieldOnCost, 9)
    expect(mapped.developmentSpreadBps).toBeCloseTo(r.capRateSpreadBps / 10000, 9)
    expect(mapped.ltc).toBe(BASE.ltcPct)
    expect(mapped.netSaleProceeds).toBeUndefined() // not in the v2 sidebar list
  })

  it('omits all-equity leverage metrics rather than showing garbage', () => {
    const r = computeQuickScreen({ ...BASE, ltcPct: 0 })
    const mapped = mapQuickScreenToOutputMetrics(r, { ...BASE, ltcPct: 0 })
    expect(mapped.debtYield).toBeUndefined()
    expect(mapped.loanConstant).toBeUndefined()
    expect(mapped.minDscr).toBeUndefined()
  })
})

describe('sensitivity grid', () => {
  it('is a 5x5 grid whose center cell matches the base case', () => {
    const grid = computeQuickScreenSensitivityGrid(BASE, 'spread')
    expect(grid.length).toBe(5)
    expect(grid[2].length).toBe(5)
    const center = grid[2][2]
    expect(center.isCenter).toBe(true)
    const base = computeQuickScreen(BASE)
    expect(center.value).toBeCloseTo(base.capRateSpreadBps / 10000, 9)
    expect(center.tier).toBe(base.feasibility)
  })

  it('supports the yield-on-cost metric toggle', () => {
    const grid = computeQuickScreenSensitivityGrid(BASE, 'yieldOnCost')
    const base = computeQuickScreen(BASE)
    expect(grid[2][2].value).toBeCloseTo(base.yieldOnCost, 9)
  })
})

describe('URL persistence', () => {
  it('round-trips through serialize/parse', () => {
    const params = serializeQuickScreenInputs(BASE)
    const parsed = parseQuickScreenInputs(params)
    expect(parsed).not.toBeNull()
    expect(parsed).toEqual(BASE)
  })

  it('returns null when there are no quick-screen params present', () => {
    expect(parseQuickScreenInputs(new URLSearchParams('foo=bar'))).toBeNull()
  })
})
