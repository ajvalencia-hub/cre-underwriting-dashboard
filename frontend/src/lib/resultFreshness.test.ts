import { describe, expect, it } from 'vitest'
import { inputsKey, isStale, latestStamp, pickMetric, stampResult } from './resultFreshness'

describe('result freshness', () => {
  it('fingerprints inputs independent of key order and undefined fields', () => {
    expect(inputsKey({ a: 1, b: { y: 2, x: 1 } })).toBe(inputsKey({ b: { x: 1, y: 2 }, a: 1, c: undefined }))
    expect(inputsKey({ a: 1 })).not.toBe(inputsKey({ a: 2 }))
    expect(inputsKey({ rows: [{ a: 1 }, { a: 2 }] })).not.toBe(inputsKey({ rows: [{ a: 2 }, { a: 1 }] }))
  })

  it('goes stale when inputs change or the deal changes', () => {
    const values = { purchasePrice: 10_000_000 }
    const stamp = stampResult('native', values, 'deal-1', 1000)
    expect(isStale(stamp, inputsKey(values), 'deal-1')).toBe(false)
    expect(isStale(stamp, inputsKey({ purchasePrice: 11_000_000 }), 'deal-1')).toBe(true)
    expect(isStale(stamp, inputsKey(values), 'deal-2')).toBe(true)
  })

  it('shows the most recent result per metric, whichever source it came from', () => {
    const native = { stamp: stampResult('native', {}, 'd', 2000), outputs: { leveredIrr: 0.14, equityMultiple: 1.9 } }
    const excel = { stamp: stampResult('excel', {}, 'd', 1000), outputs: { leveredIrr: 0.12 } }
    // Newer engine run beats an older template read-back (the old ladder
    // kept the template number forever).
    expect(pickMetric('leveredIrr', [native, excel])?.stamp.source).toBe('native')
    const newerExcel = { ...excel, stamp: { ...excel.stamp, at: 3000 } }
    expect(pickMetric('leveredIrr', [native, newerExcel])?.value).toBe(0.12)
    // Template didn't return this metric: fall back to the engine's.
    expect(pickMetric('equityMultiple', [native, newerExcel])?.stamp.source).toBe('native')
    expect(pickMetric('gpIrr', [native, newerExcel])).toBeNull()
    expect(latestStamp(native.stamp, newerExcel.stamp)?.source).toBe('excel')
  })
})
