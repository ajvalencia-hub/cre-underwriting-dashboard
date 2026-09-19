import { describe, expect, it } from 'vitest'
import type { Comp, DealMetrics, PortfolioRollup } from './api'
import type { CompareColumn, CompareRow } from './compareMath'
import {
  DEALFLOW_SLOT,
  assignCompareSlots,
  compareFamilyCharts,
  compMetric,
  compScatterPoints,
  compStripValues,
  compSubjectFromValues,
  foldTail,
  irrVsEquitySeries,
  sameSlots,
  stageEquity,
} from './portfolioChartData'
import type { OutputMetric } from '../types/schema'

describe('foldTail', () => {
  it('sorts high to low and keeps short lists whole', () => {
    expect(foldTail([{ label: 'a', value: 1 }, { label: 'b', value: 3 }]).map((r) => r.label)).toEqual(['b', 'a'])
  })
  it('folds beyond max into Other (top max-1 + Other)', () => {
    const rows = Array.from({ length: 10 }, (_, i) => ({ label: `m${i}`, value: i + 1 }))
    const out = foldTail(rows, 8)
    expect(out).toHaveLength(8)
    expect(out[0]).toEqual({ label: 'm9', value: 10 })
    expect(out[7]).toEqual({ label: 'Other (3)', value: 1 + 2 + 3 })
  })
  it('drops non-finite values', () => {
    expect(foldTail([{ label: 'x', value: NaN }, { label: 'y', value: 2 }])).toEqual([{ label: 'y', value: 2 }])
  })
})

describe('irrVsEquitySeries', () => {
  const deal = (over: Partial<PortfolioRollup['deals'][number]>): PortfolioRollup['deals'][number] => ({
    id: 'x', name: 'X', status: 'screening', dealType: 'acquisition', market: 'M', assetClass: 'mf',
    equity: 1_000_000, leveredIrr: 0.12, equityMultiple: 1.8, ...over,
  })
  it('splits by dealflow with fixed slots and skips deals without an IRR', () => {
    const { series, missing } = irrVsEquitySeries([
      deal({ id: 'a', name: 'A' }),
      deal({ id: 'b', name: 'B', dealType: 'untyped', leveredIrr: 0.2 }),
      deal({ id: 'c', name: 'C', leveredIrr: null }),
    ])
    expect(missing).toBe(1)
    expect(series.map((s) => [s.key, s.slot])).toEqual([
      ['acquisition', DEALFLOW_SLOT.acquisition],
      ['untyped', DEALFLOW_SLOT.untyped],
    ])
    expect(series[0].points).toEqual([{ x: 1_000_000, y: 0.12, label: 'A' }])
  })
  it('returns no series when nothing has an IRR', () => {
    expect(irrVsEquitySeries([deal({ leveredIrr: null })]).series).toEqual([])
  })
})

describe('stageEquity', () => {
  const ok = (equity: number | null): DealMetrics => ({
    status: 'ok', totalCost: 1, equity, leveredIrr: 0.1, equityMultiple: 1.5, yieldOnCost: null, goingInCapRate: null,
  })
  it('orders stages by the registry, omits empty stages and sums equity', () => {
    const out = stageEquity(
      'acquisition',
      [
        { id: '1', status: 'loi' },
        { id: '2', status: 'screening' },
        { id: '3', status: 'screening' },
        { id: '4', status: 'loi' },
      ],
      { '1': ok(5), '2': ok(1), '3': ok(2), '4': { status: 'incomplete', missing: ['x'] } },
    )
    expect(out.stages).toEqual(['screening', 'loi'])
    expect(out.categories).toEqual(['Screening · 2', 'LOI · 2'])
    expect(out.values).toEqual([3, 5])
    expect(out.notComputed).toBe(1)
    expect(out.totalEquity).toBe(8)
  })
  it('appends a legacy stage after the board stages and uses null when nothing computes', () => {
    const out = stageEquity('acquisition', [{ id: '1', status: 'construction' }, { id: '2', status: 'closed' }], null)
    expect(out.stages).toEqual(['closed', 'construction'])
    expect(out.values).toEqual([null, null])
    expect(out.notComputed).toBe(2)
  })
})

describe('compare slots and families', () => {
  it('keeps a deal on its slot when another leaves, newcomers take the lowest free slot', () => {
    const first = assignCompareSlots(['a', 'b', 'c'], {})
    expect(first).toEqual({ a: 1, b: 2, c: 3 })
    const second = assignCompareSlots(['b', 'c', 'd'], first)
    expect(second).toEqual({ b: 2, c: 3, d: 1 })
    expect(sameSlots(first, { ...first })).toBe(true)
    expect(sameSlots(first, second)).toBe(false)
  })

  const metric = (id: string, type: OutputMetric['type']): OutputMetric => ({ id, label: id.toUpperCase(), type })
  const columns: CompareColumn[] = [
    { dealId: 'a', name: 'Alpha', dealType: 'acquisition', outputs: {} },
    { dealId: 'b', name: 'Beta', dealType: 'development', outputs: {} },
    { dealId: 'c', name: 'Gamma', dealType: null, outputs: null },
  ]
  const rows: CompareRow[] = [
    { metric: metric('leveredIrr', 'percent'), values: [0.1, 0.15, null], applicable: [true, true, true], best: 1 },
    { metric: metric('goingInCapRate', 'percent'), values: [0.05, null, null], applicable: [true, true, true], best: null },
    { metric: metric('equityMultiple', 'multiple'), values: [null, null, null], applicable: [true, true, true], best: null },
    { metric: metric('npv', 'currency'), values: [100, -50, null], applicable: [true, true, true], best: 0 },
  ]
  it('groups the table rows into unit families with the table best picks', () => {
    const charts = compareFamilyCharts(rows, columns, { a: 2, b: 1, c: 3 })
    expect(charts.map((c) => c.key)).toEqual(['returns', 'money'])
    const ret = charts[0]
    expect(ret.categories).toEqual(['Levered IRR', 'Going-in cap'])
    expect(ret.series.map((s) => [s.key, s.slot])).toEqual([['a', 2], ['b', 1]])
    expect(ret.series[1].values).toEqual([0.15, null])
    expect(ret.best).toEqual([{ metric: 'Levered IRR', deal: 'Beta' }])
    expect(charts[1].best).toEqual([{ metric: 'NPV', deal: 'Alpha' }])
    expect(charts[1].type).toBe('currency')
  })
  it('returns nothing when no column computed', () => {
    expect(compareFamilyCharts(rows, [columns[2]], {})).toEqual([])
  })
})

describe('comps', () => {
  const comp = (over: Partial<Comp>): Comp => ({
    id: 'x', kind: 'sale', name: 'X', address: '', market: '', submarket: '', propertyType: '', source: '', notes: '',
    createdAt: '', ...over,
  })
  it('derives rent per SF and reads stored metrics', () => {
    expect(compMetric(comp({ avgRent: 2000, avgSf: 1000 }), 'rentPerSf')).toBe(2)
    expect(compMetric(comp({ avgRent: 2000, avgSf: 0 }), 'rentPerSf')).toBeNull()
    expect(compMetric(comp({ capRatePct: 0.05 }), 'capRatePct')).toBe(0.05)
    expect(compMetric(comp({ pricePerUnit: null }), 'pricePerUnit')).toBeNull()
  })
  it('needs two values for a strip', () => {
    expect(compStripValues([comp({ pricePerUnit: 1 })], 'pricePerUnit')).toEqual([])
    expect(compStripValues([comp({ name: 'A', pricePerUnit: 1 }), comp({ name: 'B', pricePerUnit: 2 }), comp({})], 'pricePerUnit')).toEqual([
      { value: 1, label: 'A' },
      { value: 2, label: 'B' },
    ])
  })
  it('needs three complete pairs for a scatter', () => {
    const list = [comp({ name: 'A', yearBuilt: 1990, pricePerUnit: 1 }), comp({ name: 'B', yearBuilt: 2000, pricePerUnit: 2 })]
    const px = (c: Comp) => c.yearBuilt
    const py = (c: Comp) => c.pricePerUnit
    expect(compScatterPoints(list, px, py)).toEqual([])
    const three = [...list, comp({ name: 'C', yearBuilt: 2010, pricePerUnit: 3 }), comp({ name: 'D', yearBuilt: null, pricePerUnit: 3 })]
    expect(compScatterPoints(three, px, py)).toHaveLength(3)
  })
  it('derives the subject from the deal inputs', () => {
    const s = compSubjectFromValues({
      dealType: 'acquisition',
      purchasePrice: 10_000_000,
      exitCapRatePct: 0.055,
      unitMix: [
        { unitCount: 40, avgSf: 800, inPlaceRent: 1500 },
        { unitCount: 60, avgSf: 1000, marketRent: 2000 },
      ],
    })
    expect(s.pricePerUnit).toBe(100_000)
    expect(s.pricePerSf).toBeCloseTo(10_000_000 / 92_000)
    expect(s.avgRent).toBe(1800)
    expect(s.rentPerSf).toBeCloseTo((40 * 1500 + 60 * 2000) / 92_000)
    expect(s.capRatePct).toBe(0.055)
  })
  it('omits price metrics for a development and handles empty values', () => {
    const s = compSubjectFromValues({ dealType: 'development', purchasePrice: 1_000_000, unitMix: [{ unitCount: 10 }] })
    expect(s.pricePerUnit).toBeUndefined()
    expect(s.avgRent).toBeUndefined()
    expect(compSubjectFromValues(null)).toEqual({})
  })
})
