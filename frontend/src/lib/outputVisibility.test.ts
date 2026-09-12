import { describe, expect, it } from 'vitest'
import { isOutputVisibleFor, visibleOutputsFor } from './outputVisibility'

describe('isOutputVisibleFor', () => {
  it('hides development-only metrics on acquisitions', () => {
    expect(isOutputVisibleFor('developmentSpreadBps', 'acquisition')).toBe(false)
    expect(isOutputVisibleFor('combinedLtc', 'acquisition')).toBe(false)
    expect(isOutputVisibleFor('residentialYieldOnCost', 'acquisition')).toBe(false)
    expect(isOutputVisibleFor('leveredIrr', 'acquisition')).toBe(true)
    expect(isOutputVisibleFor('postRenoAvgRent', 'acquisition')).toBe(true)
  })

  it('hides acquisition-only metrics on developments', () => {
    expect(isOutputVisibleFor('postRenoAvgRent', 'development')).toBe(false)
    expect(isOutputVisibleFor('developmentSpreadBps', 'development')).toBe(true)
  })

  it('shows everything for untyped deals', () => {
    expect(isOutputVisibleFor('developmentSpreadBps', null)).toBe(true)
    expect(isOutputVisibleFor('postRenoAvgRent', null)).toBe(true)
  })
})

describe('visibleOutputsFor', () => {
  it('filters a metric list in place order', () => {
    const metrics = [{ id: 'leveredIrr' }, { id: 'developmentSpreadBps' }, { id: 'ltv' }]
    expect(visibleOutputsFor(metrics, 'acquisition').map((m) => m.id)).toEqual(['leveredIrr', 'ltv'])
    expect(visibleOutputsFor(metrics, 'development')).toHaveLength(3)
  })
})
