import { describe, expect, it } from 'vitest'
import {
  METRIC_DIRECTION,
  bestValueIndex,
  buildComparisonRows,
  tornadoGeometry,
} from './scenarioComparison'
import type { InputSchema } from '../types/schema'
import type { Scenario } from '../types/scenario'

const SCHEMA = {
  version: 1,
  dealTypes: [],
  propertyTypes: [],
  outputs: [],
  sections: [
    {
      id: 'a',
      label: 'Section A',
      visibleWhen: null,
      fields: [
        { id: 'x', label: 'X', type: 'number' },
        { id: 'y', label: 'Y', type: 'currency' },
      ],
    },
  ],
} as unknown as InputSchema

function scenario(inputs: Record<string, unknown>): Scenario {
  return {
    id: Math.random().toString(36),
    scenarioName: 's',
    kind: 'full',
    dealId: null,
    templateId: null,
    mappingProfileId: null,
    inputs,
    outputs: {},
    createdAt: '',
    updatedAt: '',
  } as Scenario
}

describe('buildComparisonRows', () => {
  it('marks differing rows and groups by section, including extra keys', () => {
    const rows = buildComparisonRows(SCHEMA, [
      scenario({ x: 1, y: 5, custom: 'a' }),
      scenario({ x: 2, y: 5, custom: 'a' }),
    ])
    const byId = Object.fromEntries(rows.map((r) => [r.fieldId, r]))
    expect(byId.x.differs).toBe(true)
    expect(byId.y.differs).toBe(false)
    expect(byId.x.sectionLabel).toBe('Section A')
    expect(byId.custom.sectionLabel).toBe('Other')
    expect(byId.custom.differs).toBe(false)
  })

  it('treats missing values as differing when another scenario has one', () => {
    const rows = buildComparisonRows(SCHEMA, [scenario({ x: 1 }), scenario({})])
    expect(rows.find((r) => r.fieldId === 'x')?.differs).toBe(true)
  })
})

describe('bestValueIndex', () => {
  it('respects direction per metric', () => {
    expect(bestValueIndex('leveredIrr', [0.1, 0.15, 0.12])).toBe(1) // up
    expect(bestValueIndex('paybackPeriodYears', [6, 4.5, 5])).toBe(1) // down
    expect(bestValueIndex('breakEvenRatio', [0.7, 0.65])).toBe(1) // down
  })

  it('returns null for ambiguous metrics, ties, and sparse data', () => {
    expect(bestValueIndex('ltv', [0.6, 0.7])).toBeNull() // no direction encoded
    expect(bestValueIndex('goingInCapRate', [0.05, 0.06])).toBeNull() // buyer/seller ambiguity
    expect(bestValueIndex('leveredIrr', [0.1, 0.1])).toBeNull() // tie
    expect(bestValueIndex('leveredIrr', [0.1, null])).toBeNull() // one value only
  })

  it('every direction key targets a plausible metric', () => {
    for (const direction of Object.values(METRIC_DIRECTION)) {
      expect(['up', 'down']).toContain(direction)
    }
  })
})

describe('tornadoGeometry', () => {
  const fmt = (v: number) => v.toFixed(3)

  it('scales the widest swing to the chart edges and centers the base', () => {
    const bars = [
      { key: 'a', label: 'A', low: 0.05, high: 0.15, impact: 0.05 },
      { key: 'b', label: 'B', low: 0.09, high: 0.11, impact: 0.01 },
    ]
    const geometry = tornadoGeometry(bars, 0.1, fmt)
    expect(geometry[0].x0).toBeCloseTo(0.0, 9) // base 0.1, swing 0.05 spans half-width
    expect(geometry[0].x1).toBeCloseTo(1.0, 9)
    expect(geometry[1].x0).toBeCloseTo(0.4, 9)
    expect(geometry[1].x1).toBeCloseTo(0.6, 9)
  })

  it('keeps label anchors on the side each perturbation landed', () => {
    // Down-perturbed cap -> HIGHER value: low lands right of high.
    const geometry = tornadoGeometry(
      [{ key: 'cap', label: 'Cap', low: 0.14, high: 0.07, impact: 0.04 }],
      0.1,
      fmt,
    )
    expect(geometry[0].lowX).toBeGreaterThan(geometry[0].highX)
    expect(geometry[0].lowLabel).toBe('0.140')
  })

  it('nulls fall back to the base position with an em-dash label', () => {
    const geometry = tornadoGeometry(
      [{ key: 'x', label: 'X', low: null, high: 0.12, impact: 0.02 }],
      0.1,
      fmt,
    )
    expect(geometry[0].lowX).toBeCloseTo(0.5, 9)
    expect(geometry[0].lowLabel).toBe('—')
  })
})
