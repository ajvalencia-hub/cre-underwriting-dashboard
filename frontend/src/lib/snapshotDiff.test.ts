import { describe, expect, it } from 'vitest'
import { diffSnapshots, formatDiffValue } from './snapshotDiff'
import type { InputSchema } from '../types/schema'

const schema = {
  sections: [
    {
      id: 'exit',
      label: 'Exit Assumptions',
      visibleWhen: null,
      fields: [
        { id: 'exitCapRatePct', label: 'Exit Cap Rate', type: 'percent' },
        { id: 'purchasePrice', label: 'Purchase Price', type: 'currency' },
      ],
    },
    {
      id: 'income',
      label: 'Operating Income',
      visibleWhen: null,
      fields: [{ id: 'unitMix', label: 'Unit Mix', type: 'table', columns: [] }],
    },
  ],
  outputs: [],
} as unknown as InputSchema

describe('scalar diffing + formatting', () => {
  it('formats per field type and classifies kinds', () => {
    const diff = diffSnapshots(
      { exitCapRatePct: 0.055, purchasePrice: 1_000_000 },
      { exitCapRatePct: 0.0525, custom: 'x' },
      schema,
    )
    const byId = Object.fromEntries(diff.scalars.map((s) => [s.fieldId, s]))
    expect(byId.exitCapRatePct.kind).toBe('changed')
    expect(byId.exitCapRatePct.section).toBe('Exit Assumptions')
    expect(formatDiffValue(byId.exitCapRatePct.before, 'percent')).toBe('5.50%')
    expect(formatDiffValue(byId.exitCapRatePct.after, 'percent')).toBe('5.25%')
    expect(byId.purchasePrice.kind).toBe('removed')
    expect(formatDiffValue(1_000_000, 'currency')).toBe('$1,000,000')
    expect(byId.custom.kind).toBe('added')
    expect(byId.custom.section).toBe('Other')
    expect(formatDiffValue(null, 'text')).toBe('—')
  })

  it('nests into the quickScreen blob', () => {
    const diff = diffSnapshots(
      { quickScreen: { rent: 1800, units: 100 } },
      { quickScreen: { rent: 2000, units: 100 } },
      schema,
    )
    expect(diff.scalars).toHaveLength(1)
    expect(diff.scalars[0].fieldId).toBe('quickScreen.rent')
    expect(diff.scalars[0].section).toBe('Quick Screen')
  })
})

describe('table diffing by row key', () => {
  const before = {
    unitMix: [
      { unitType: '1BR', unitCount: 10, inPlaceRent: 1500 },
      { unitType: '2BR', unitCount: 5, inPlaceRent: 2000 },
    ],
  }

  it('classifies added/removed/changed rows and ignores reordering', () => {
    const after = {
      unitMix: [
        { unitType: '2BR', unitCount: 5, inPlaceRent: 2000 }, // reordered, unchanged
        { unitType: '1BR', unitCount: 12, inPlaceRent: 1500 }, // changed count
        { unitType: 'Studio', unitCount: 4, inPlaceRent: 1200 }, // added
      ],
    }
    const diff = diffSnapshots(before, after, schema)
    expect(diff.tables).toHaveLength(1)
    const rows = Object.fromEntries(diff.tables[0].rows.map((r) => [r.key, r]))
    expect(rows['1BR'].kind).toBe('changed')
    expect(rows['1BR'].cells).toEqual([{ column: 'unitCount', before: 10, after: 12 }])
    expect(rows['Studio'].kind).toBe('added')
    expect(rows['2BR']).toBeUndefined() // pure reorder is not a change

    const removal = diffSnapshots(before, { unitMix: [before.unitMix[0]] }, schema)
    expect(removal.tables[0].rows).toEqual([{ key: '2BR', kind: 'removed', cells: [] }])
  })

  it('keys lease rows by suiteId even without a schema entry', () => {
    const diff = diffSnapshots(
      { commercialLeases: [{ suiteId: '100', baseRentPsfAnnual: 30 }] },
      { commercialLeases: [{ suiteId: '100', baseRentPsfAnnual: 32 }] },
      schema,
    )
    expect(diff.tables[0].rows[0]).toMatchObject({
      key: '100',
      kind: 'changed',
      cells: [{ column: 'baseRentPsfAnnual', before: 30, after: 32 }],
    })
  })

  it('disambiguates duplicate row keys instead of dropping rows', () => {
    const diff = diffSnapshots(
      { opexLineItems: [{ category: 'taxes', amount: 1 }, { category: 'taxes', amount: 2 }] },
      { opexLineItems: [{ category: 'taxes', amount: 1 }] },
      schema,
    )
    expect(diff.tables[0].rows).toEqual([{ key: "taxes'", kind: 'removed', cells: [] }])
  })
})

describe('restore preview correctness', () => {
  it('the current->target diff lists exactly what a restore would change', () => {
    const current = { exitCapRatePct: 0.06, purchasePrice: 900_000, untouched: 'same' }
    const target = { exitCapRatePct: 0.055, purchasePrice: 900_000, untouched: 'same' }
    const diff = diffSnapshots(current, target, schema)
    expect(diff.scalars.map((s) => s.fieldId)).toEqual(['exitCapRatePct'])
    expect(diff.tables).toEqual([])
    // Applying the target reproduces it: nothing left to diff.
    expect(diffSnapshots(target, target, schema)).toEqual({ scalars: [], tables: [] })
  })
})
