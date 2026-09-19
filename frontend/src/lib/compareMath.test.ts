import { describe, expect, it } from 'vitest'
import {
  MAX_COMPARE_DEALS,
  METRIC_DIRECTION,
  bestValueIndex,
  buildCompareRows,
  compareToCsv,
  dealFormValues,
  loadCompareIds,
  pruneCompareIds,
  saveCompareIds,
  toggleCompareId,
  type CompareColumn,
} from './compareMath'
import * as scenarioComparison from './scenarioComparison'
import { ACQUISITION_QUICK_SCREEN_INPUTS_KEY, QUICK_SCREEN_INPUTS_KEY, QUICK_SCREEN_MODE_KEY } from './dealPersistence'
import type { OutputMetric } from '../types/schema'

function memoryStorage() {
  const data: Record<string, string> = {}
  return {
    getItem: (key: string) => (key in data ? data[key] : null),
    setItem: (key: string, value: string) => {
      data[key] = value
    },
  }
}

const METRICS: OutputMetric[] = [
  { id: 'leveredIrr', label: 'Levered IRR', type: 'percent' },
  { id: 'paybackPeriodYears', label: 'Payback', type: 'years' },
  { id: 'developmentSpreadBps', label: 'Dev spread', type: 'number' },
  { id: 'postRenoAvgRent', label: 'Post-reno rent', type: 'currency' },
  { id: 'grossMarginPct', label: 'Gross margin', type: 'percent' },
]

const columns: CompareColumn[] = [
  { dealId: 'a', name: 'Alpha', dealType: 'acquisition', outputs: { leveredIrr: 0.12, paybackPeriodYears: 6, postRenoAvgRent: 2000 } },
  { dealId: 'b', name: 'Beta, "dev"', dealType: 'development', outputs: { leveredIrr: 0.15, paybackPeriodYears: 5, developmentSpreadBps: 150 } },
  { dealId: 'c', name: 'Gamma', dealType: null, outputs: null, note: 'untyped' },
]

describe('best value', () => {
  it('is the one table behind the scenario comparison too', () => {
    expect(scenarioComparison.METRIC_DIRECTION).toBe(METRIC_DIRECTION)
    expect(scenarioComparison.bestValueIndex).toBe(bestValueIndex)
  })

  it('respects direction, ties and ambiguous metrics', () => {
    expect(bestValueIndex('leveredIrr', [0.1, 0.2, null])).toBe(1)
    expect(bestValueIndex('paybackPeriodYears', [6, 5])).toBe(1)
    expect(bestValueIndex('leveredIrr', [0.2, 0.2])).toBeNull()
    expect(bestValueIndex('goingInCapRate', [0.05, 0.06])).toBeNull()
    expect(bestValueIndex('leveredIrr', [0.2, null])).toBeNull()
  })
})

describe('selection persistence', () => {
  it('round-trips through storage and caps at the maximum', () => {
    const storage = memoryStorage()
    expect(loadCompareIds(storage)).toEqual([])
    saveCompareIds(storage, ['a', 'b', 'c', 'd', 'e'])
    expect(loadCompareIds(storage)).toEqual(['a', 'b', 'c', 'd'])
  })

  it('tolerates junk and duplicates', () => {
    const storage = memoryStorage()
    storage.setItem('cre.compareDealIds', '{nope')
    expect(loadCompareIds(storage)).toEqual([])
    storage.setItem('cre.compareDealIds', '[1, "x", null, "x"]')
    expect(loadCompareIds(storage)).toEqual(['x'])
  })

  it('survives a throwing store', () => {
    const broken = {
      getItem: () => {
        throw new Error('SecurityError')
      },
      setItem: () => {
        throw new Error('QuotaExceeded')
      },
    }
    expect(loadCompareIds(broken)).toEqual([])
    expect(() => saveCompareIds(broken, ['a'])).not.toThrow()
  })

  it('toggles and refuses a fifth selection', () => {
    expect(toggleCompareId([], 'a')).toEqual(['a'])
    expect(toggleCompareId(['a', 'b'], 'a')).toEqual(['b'])
    const full = ['a', 'b', 'c', 'd']
    expect(full).toHaveLength(MAX_COMPARE_DEALS)
    expect(toggleCompareId(full, 'e')).toEqual(full)
  })

  it('prunes ids that no longer exist', () => {
    expect(pruneCompareIds(['a', 'zz'], [{ id: 'a' }])).toEqual(['a'])
  })
})

describe('dealFormValues', () => {
  it('strips the quick-screen persistence keys and fills schema defaults', () => {
    expect(
      dealFormValues(
        {
          purchasePrice: 1,
          [QUICK_SCREEN_INPUTS_KEY]: {},
          [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: {},
          [QUICK_SCREEN_MODE_KEY]: 'development',
        },
        { holdYears: 5, purchasePrice: 0 },
      ),
    ).toEqual({ holdYears: 5, purchasePrice: 1 })
  })
})

describe('buildCompareRows', () => {
  const rows = buildCompareRows(METRICS, columns)
  const byId = Object.fromEntries(rows.map((r) => [r.metric.id, r]))

  it('keeps a metric when it applies to at least one column and flags n/a cells', () => {
    expect(byId.developmentSpreadBps.applicable).toEqual([false, true, true])
    expect(byId.postRenoAvgRent.applicable).toEqual([true, false, true])
    // Untyped deals see everything, but have nothing computed.
    expect(byId.leveredIrr.values).toEqual([0.12, 0.15, null])
  })

  it('drops a metric no computed deal produced', () => {
    expect(byId.grossMarginPct).toBeUndefined()
  })

  it('keeps every applicable row while nothing is computed yet', () => {
    const pending = buildCompareRows(METRICS, [{ dealId: 'x', name: 'X', dealType: null, outputs: null }])
    expect(pending.map((r) => r.metric.id)).toContain('grossMarginPct')
  })

  it('highlights the best value with the metric direction', () => {
    expect(byId.leveredIrr.best).toBe(1) // up
    expect(byId.paybackPeriodYears.best).toBe(1) // down: 5 beats 6
    expect(byId.developmentSpreadBps.best).toBeNull() // one numeric value only
  })
})

describe('compareToCsv', () => {
  it('quotes names with commas/quotes and writes n/a for inapplicable cells', () => {
    const rows = buildCompareRows(METRICS, columns)
    const csv = compareToCsv(rows, columns, (m, v) => (m.type === 'percent' ? `${(v * 100).toFixed(1)}%` : String(v)))
    const lines = csv.split('\n')
    expect(lines[0]).toBe('Metric,Alpha,"Beta, ""dev""",Gamma')
    expect(lines[1]).toBe('Levered IRR,12.0%,15.0%,')
    expect(lines[3]).toBe('Dev spread,n/a,150,')
  })
})
