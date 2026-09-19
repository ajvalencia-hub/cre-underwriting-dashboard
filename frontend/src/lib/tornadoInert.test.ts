import { describe, expect, it } from 'vitest'
import { tornadoGeometry } from './scenarioComparison'

// Kept apart from scenarioComparison.test.ts (owned by another port group).
describe('tornado inert drivers (Run 6)', () => {
  it('passes the inert flag and reason through the geometry', () => {
    const bars = [
      { key: 'rent', label: 'Rent', low: 0.1, high: 0.14, impact: 0.04 },
      { key: 'opex', label: 'Opex', low: 0.12, high: 0.12, impact: 0, inert: true, reason: 'opex detail mode' },
      { key: 'cap', label: 'Cap', low: 0.11, high: 0.13, impact: 0.01, inert: false, reason: null },
    ]
    const geometry = tornadoGeometry(bars, 0.12, (v) => v.toFixed(2))
    expect(geometry.map((g) => g.inert)).toEqual([false, true, false])
    expect(geometry[1].reason).toBe('opex detail mode')
    expect(geometry[0].reason).toBeUndefined()
    expect(geometry[2].reason).toBeUndefined()
  })
})
