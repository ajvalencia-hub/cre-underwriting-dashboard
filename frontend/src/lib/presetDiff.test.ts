import { describe, expect, it } from 'vitest'
import { presetDiff, selectedChanges } from './presetDiff'

describe('presetDiff', () => {
  it('marks changed and unchanged rows', () => {
    const rows = presetDiff(
      { vacancyPct: 0.05, exitCapRatePct: 0.06 },
      { vacancyPct: 0.07, exitCapRatePct: 0.06 },
    )
    expect(rows).toEqual([
      { fieldId: 'vacancyPct', current: 0.05, proposed: 0.07, changed: true },
      { fieldId: 'exitCapRatePct', current: 0.06, proposed: 0.06, changed: false },
    ])
  })

  it('treats a missing current value as a change', () => {
    const rows = presetDiff({}, { holdPeriodYears: 5 })
    expect(rows[0].changed).toBe(true)
  })

  it('tolerates float noise', () => {
    const rows = presetDiff({ rentGrowthPct: 0.1 + 0.2 }, { rentGrowthPct: 0.3 })
    expect(rows[0].changed).toBe(false)
  })

  it('skips null preset values', () => {
    expect(presetDiff({ a: 1 }, { a: null })).toEqual([])
  })
})

describe('selectedChanges', () => {
  it('builds a patch from checked, changed rows only', () => {
    const rows = presetDiff(
      { vacancyPct: 0.05, exitCapRatePct: 0.06, holdPeriodYears: 5 },
      { vacancyPct: 0.07, exitCapRatePct: 0.06, holdPeriodYears: 7 },
    )
    const patch = selectedChanges(rows, new Set(['vacancyPct', 'exitCapRatePct']))
    // exitCapRatePct is selected but unchanged; holdPeriodYears changed but unselected
    expect(patch).toEqual({ vacancyPct: 0.07 })
  })
})
