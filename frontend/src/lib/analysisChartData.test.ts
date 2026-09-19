import { describe, expect, it } from 'vitest'
import {
  annualOperating,
  cumulativeLevered,
  devCostBreakdown,
  exceedanceCurve,
  forwardCurvePath,
  hasAnyDebt,
  heatTint,
  histogramByHurdle,
  holdSweepSeries,
  loanBalanceByYear,
  metricFamilies,
  nextFreeSlot,
  noiSplit,
  paybackLabel,
  renovationByMonth,
  scenarioCell,
  sweepLine,
} from './analysisChartData'
import type { Statement } from './cashflowStatement'

/** 24 operating months + close: NOI 100/mo, DS 60/mo, equity 1,000 at close,
 *  sale nets 1,500 in month 24. */
function statement(overrides: Partial<Statement> = {}): Statement {
  const n = 25
  const z = () => new Array<number>(n).fill(0)
  const noi = z().map((_, i) => (i === 0 ? 0 : 100))
  const debtService = z().map((_, i) => (i === 0 ? 0 : 60))
  const sale = z()
  sale[24] = 1500
  const levered = z().map((_, i) => (i === 0 ? -1000 : noi[i] - debtService[i] + sale[i]))
  const loanBalance = z().map((_, i) => 2000 - i * 10)
  return {
    months: Array.from({ length: n }, (_, i) => i),
    phases: new Array(n).fill('stabilized'),
    constructionMonths: 0,
    stabilizationMonth: 0,
    exitMonth: 24,
    gpr: z(), vacancyLoss: z(), creditLoss: z(), otherIncome: z(), egi: z(),
    fixedOpexByCategory: {}, managementFee: z(), opexTotal: z(),
    noi, occupancy: z(), costs: z(), loanFees: z(), equityFunded: z(), debtDraws: z(),
    interest: z(), principal: z(), debtService, loanBalance,
    saleProceedsNet: sale, saleProceedsGross: z(), recoveries: z(), leasingCapital: z(),
    unlevered: z(), levered, lpDistributions: z(), gpDistributions: z(),
    ...overrides,
  }
}

describe('annualOperating', () => {
  it('sums months into years, strips the sale from levered CF and ratios DSCR', () => {
    const a = annualOperating(statement())
    expect(a.years).toEqual(['Y1', 'Y2'])
    expect(a.noi).toEqual([1200, 1200])
    expect(a.debtService).toEqual([720, 720])
    expect(a.leveredOperating).toEqual([480, 480])
    expect(a.dscr[0]).toBeCloseTo(1200 / 720)
    expect(a.hasDebt).toBe(true)
    expect(a.hasOperations).toBe(true)
  })
  it('reports no DSCR without debt and no operations for a zero-NOI deal', () => {
    const zeros = new Array(25).fill(0)
    const a = annualOperating(statement({ debtService: zeros, noi: zeros }))
    expect(a.dscr).toEqual([null, null])
    expect(a.hasDebt).toBe(false)
    expect(a.hasOperations).toBe(false)
  })
  it('handles a partial final year', () => {
    const s = statement()
    const cut = (v: number[]) => v.slice(0, 19)
    const a = annualOperating({ ...s, months: cut(s.months), noi: cut(s.noi), debtService: cut(s.debtService), levered: cut(s.levered), saleProceedsNet: cut(s.saleProceedsNet) })
    expect(a.years).toEqual(['Y1', 'Y2'])
    expect(a.noi).toEqual([1200, 600])
  })
})

describe('year-end series', () => {
  it('reads the loan balance at close and each year end', () => {
    expect(loanBalanceByYear(statement())).toEqual({ x: ['Close', 'Y1', 'Y2'], values: [2000, 1880, 1760] })
    expect(hasAnyDebt(statement())).toBe(true)
    expect(hasAnyDebt(statement({ loanBalance: new Array(25).fill(0) }))).toBe(false)
  })
  it('accumulates levered cash flow into a J-curve and finds payback', () => {
    const c = cumulativeLevered(statement())
    expect(c.x).toEqual(['Close', 'Y1', 'Y2'])
    expect(c.values).toEqual([-1000, -520, 1460])
    expect(paybackLabel(c)).toBe('Y2')
    expect(paybackLabel({ x: ['Close', 'Y1'], values: [-5, -1] })).toBeNull()
    expect(paybackLabel({ x: ['Close', 'Y1'], values: [0, 3] })).toBeNull()
  })
})

describe('renovationByMonth', () => {
  it('drops the close column', () => {
    const r = renovationByMonth({
      unitsComplete: [0, 0, 2, 4],
      unitsInProgress: [0, 2, 2, 0],
      unitsRemaining: [4, 2, 0, 0],
      spendSchedule: [],
      budget: 1,
      fundingSource: 'operating_cash',
    })
    expect(r).toEqual({ months: ['M1', 'M2', 'M3'], complete: [0, 2, 4], inProgress: [2, 2, 0] })
  })
})

describe('holdSweepSeries', () => {
  it('keeps nulls as gaps', () => {
    const s = holdSweepSeries([
      { holdYear: 3, leveredIrr: 0.1, unleveredIrr: null, equityMultiple: 1.3 },
      { holdYear: 4, leveredIrr: null, unleveredIrr: 0.07, equityMultiple: null },
    ])
    expect(s).toEqual({ x: ['Y3', 'Y4'], levered: [0.1, null], unlevered: [null, 0.07], equityMultiple: [1.3, null] })
  })
})

describe('quick screen shaping', () => {
  it('builds the development cost stack in order and zeroes non-finite parts', () => {
    const parts = devCostBreakdown({ hardCosts: 10, softCosts: 2, contingency: 1, developerFee: 0.5, financingCost: NaN }, 5)
    expect(parts.map((p) => p.label)).toEqual(['Land', 'Hard costs', 'Soft costs', 'Contingency', 'Developer fee', 'Interest (est.)'])
    expect(parts.map((p) => p.value)).toEqual([5, 10, 2, 1, 0.5, 0])
  })
  it('splits NOI into debt service and cash flow, or null on bad data', () => {
    expect(noiSplit({ stabilizedNoi: 100, annualDebtService: 70, leveredCashFlow: 30 })).toEqual({ noi: 100, debtService: 70, cashFlow: 30 })
    expect(noiSplit({ stabilizedNoi: NaN, annualDebtService: 70, leveredCashFlow: 30 })).toBeNull()
  })
})

describe('sweepLine', () => {
  it('matches points by driver value and gaps missing or non-numeric outputs', () => {
    const points = [
      { driverValues: { cap: 0.05 }, outputs: { irr: 0.12 }, warnings: [] },
      { driverValues: { cap: 0.06 }, outputs: { irr: 'n/a' }, warnings: [] },
      { driverValues: { cap: 0.07 }, outputs: { irr: null }, warnings: [] },
    ]
    expect(sweepLine(points, 'cap', [0.05, 0.06, 0.07, 0.08], 'irr')).toEqual([0.12, null, null, null])
  })
})

describe('heatTint', () => {
  it('is neutral at the base and scales to the largest deviation', () => {
    expect(heatTint(0.12, 0.12, 0.02)).toEqual({ side: 'mid', strength: 0 })
    expect(heatTint(0.14, 0.12, 0.02)).toEqual({ side: 'pos', strength: 1 })
    expect(heatTint(0.11, 0.12, 0.02).side).toBe('neg')
    expect(heatTint(0.11, 0.12, 0.02).strength).toBeCloseTo(0.5)
    expect(heatTint(0.5, 0.12, 0.02).strength).toBe(1)
    expect(heatTint(NaN, 0.12, 0.02)).toEqual({ side: 'mid', strength: 0 })
    expect(heatTint(0.1, 0.12, 0)).toEqual({ side: 'mid', strength: 0 })
  })
})

describe('Monte Carlo shaping', () => {
  const bins = [
    { lo: 0.0, hi: 0.05, count: 10 },
    { lo: 0.05, hi: 0.1, count: 30 },
    { lo: 0.1, hi: 0.15, count: 60 },
  ]
  const f = (v: number) => `${Math.round(v * 100)}%`
  it('splits bins at the hurdle by lower edge', () => {
    const h = histogramByHurdle(bins, 0.1, f)
    expect(h.categories).toEqual(['0% to 5%', '5% to 10%', '10% to 15%'])
    expect(h.below).toEqual([10, 30, null])
    expect(h.above).toEqual([null, null, 60])
    expect(h.split).toBe(true)
    expect(histogramByHurdle(bins, null, f).below).toEqual([10, 30, 60])
  })
  it('builds the exceedance curve', () => {
    expect(exceedanceCurve(bins)).toEqual({ edges: [0, 0.05, 0.1], prob: [1, 0.9, 0.6] })
    expect(exceedanceCurve([])).toEqual({ edges: [], prob: [] })
    expect(exceedanceCurve([{ lo: 0, hi: 1, count: 0 }])).toEqual({ edges: [], prob: [] })
  })
})

describe('scenario shaping', () => {
  it('prefers the fresh recompute, falls back to saved while pending or failed', () => {
    expect(scenarioCell({ irr: 0.1 }, { irr: 0.12 }, 'irr')).toEqual({ value: 0.12, savedNum: 0.1, usingSaved: false, disagrees: true })
    expect(scenarioCell({ irr: 0.1 }, undefined, 'irr')).toEqual({ value: 0.1, savedNum: 0.1, usingSaved: true, disagrees: false })
    expect(scenarioCell({ irr: 0.1 }, 'failed', 'irr').value).toBe(0.1)
    expect(scenarioCell(undefined, {}, 'irr')).toEqual({ value: null, savedNum: null, usingSaved: false, disagrees: false })
    expect(scenarioCell({ irr: 0.12 }, { irr: 0.12001 }, 'irr').disagrees).toBe(false)
  })
  it('hands out the lowest free slot', () => {
    expect(nextFreeSlot([])).toBe(1)
    expect(nextFreeSlot([1, 3])).toBe(2)
    expect(nextFreeSlot([1, 2, 3, 4, 5, 6, 7, 8])).toBe(8)
  })
  it('groups metrics by unit', () => {
    const f = metricFamilies([
      { id: 'a', type: 'percent' },
      { id: 'b', type: 'multiple' },
      { id: 'c', type: 'currency' },
    ])
    expect(f.percent.map((m) => m.id)).toEqual(['a'])
    expect(f.multiple.map((m) => m.id)).toEqual(['b'])
  })
})

describe('forwardCurvePath', () => {
  it('is null unless the loan floats with a current index', () => {
    expect(forwardCurvePath({ rateMode: 'fixed', currentIndexPct: 0.04 }, 12)).toBeNull()
    expect(forwardCurvePath({ rateMode: 'floating' }, 12)).toBeNull()
  })
  it('steps the index, applies the floor, and the cap only within its term', () => {
    const p = forwardCurvePath(
      {
        rateMode: 'floating',
        currentIndexPct: 0.05,
        floorPct: 0.03,
        rateCapStrikePct: 0.045,
        rateCapTermMonths: 3,
        forwardCurve: [{ month: 5, indexPct: 0.02 }, { month: 3, indexPct: 0.04 }, { month: 'x', indexPct: 1 }],
      },
      6,
    )!
    expect(p.index).toEqual([0.05, 0.05, 0.04, 0.04, 0.02, 0.02])
    expect(p.effective).toEqual([0.045, 0.045, 0.04, 0.04, 0.03, 0.03])
    expect(p.floor).toBe(0.03)
    expect(p.strike).toBe(0.045)
    expect(p.bites).toBe(true)
  })
  it('reports no cap without a term and no bite on a plain curve', () => {
    const p = forwardCurvePath({ rateMode: 'floating', currentIndexPct: 0.04, rateCapStrikePct: 0.05 }, 3)!
    expect(p.strike).toBeNull()
    expect(p.bites).toBe(false)
    expect(p.months).toEqual([1, 2, 3])
  })
})
