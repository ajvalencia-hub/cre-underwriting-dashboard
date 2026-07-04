import { describe, expect, it } from 'vitest'
import {
  isNonEmptyUnitMix,
  mergeUnitMix,
  toSchemaRows,
  type ProposedUnitMixRow,
} from './unitMixMerge'

function proposed(unitType: string, unitCount: number, rent: number): ProposedUnitMixRow {
  return {
    unitType,
    unitCount,
    avgSf: 800,
    inPlaceRent: rent,
    marketRent: rent + 50,
    occupiedCount: unitCount - 1,
    occupancyPct: (unitCount - 1) / unitCount,
    sourceRowCount: unitCount,
  }
}

describe('toSchemaRows', () => {
  it('strips provenance columns down to the schema shape', () => {
    const rows = toSchemaRows([proposed('1BR', 10, 1400)])
    expect(rows[0]).toEqual({
      unitType: '1BR',
      unitCount: 10,
      avgSf: 800,
      inPlaceRent: 1400,
      marketRent: 1450,
    })
    expect('sourceRowCount' in rows[0]).toBe(false)
  })
})

describe('mergeUnitMix', () => {
  const existing = [
    { unitType: '1BR', unitCount: 8, avgSf: 700, inPlaceRent: 1300, marketRent: 1350 },
    { unitType: '3BR', unitCount: 4, avgSf: 1400, inPlaceRent: 2600, marketRent: 2700 },
  ]

  it('replace mode swaps the whole table', () => {
    const result = mergeUnitMix(existing, [proposed('2BR', 6, 1900)], 'replace')
    expect(result.map((r) => r.unitType)).toEqual(['2BR'])
  })

  it('merge mode replaces matching types only, keeps the rest, appends new', () => {
    const result = mergeUnitMix(
      existing,
      [proposed('1br', 10, 1400), proposed('2BR', 6, 1900)], // case-insensitive match
      'merge',
    )
    expect(result.map((r) => r.unitType)).toEqual(['1br', '3BR', '2BR'])
    expect(result[0].unitCount).toBe(10) // replaced by the proposal
    expect(result[1].unitCount).toBe(4) // untouched existing row
  })

  it('matches ignore surrounding whitespace', () => {
    const result = mergeUnitMix(existing, [proposed(' 1BR ', 12, 1500)], 'merge')
    expect(result).toHaveLength(2)
    expect(result[0].unitCount).toBe(12)
  })
})

describe('isNonEmptyUnitMix', () => {
  it('detects non-empty arrays only', () => {
    expect(isNonEmptyUnitMix([{ unitType: 'x' }])).toBe(true)
    expect(isNonEmptyUnitMix([])).toBe(false)
    expect(isNonEmptyUnitMix(undefined)).toBe(false)
    expect(isNonEmptyUnitMix('nope')).toBe(false)
  })
})
