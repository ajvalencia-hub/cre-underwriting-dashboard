import { describe, expect, it } from 'vitest'
import { describeInputChanges, inputChangesPrompt } from './inputChanges'
import type { InputSchema } from '../types/schema'

const schema = {
  sections: [
    {
      id: 'a',
      label: 'A',
      fields: [
        { id: 'purchasePrice', label: 'Purchase Price', type: 'currency', required: false },
        { id: 'vacancyPct', label: 'Vacancy', type: 'percent', required: false },
      ],
    },
  ],
  outputs: [],
} as unknown as InputSchema

describe('describeInputChanges', () => {
  it('lists overwritten values only, not newly filled ones', () => {
    const lines = describeInputChanges(schema, { purchasePrice: 100 }, { purchasePrice: 200, vacancyPct: 0.05 }, false)
    expect(lines).toHaveLength(1)
    expect(lines[0]).toMatch(/^• Purchase Price: /)
  })

  it('lists cleared values when replacing everything', () => {
    const lines = describeInputChanges(schema, { purchasePrice: 100, vacancyPct: 0.1 }, { purchasePrice: 100 }, true)
    expect(lines).toEqual([expect.stringMatching(/^• Vacancy: .* → \(cleared\)$/)])
  })

  it('keeps missing values on a merge', () => {
    expect(describeInputChanges(schema, { vacancyPct: 0.1 }, {}, false)).toEqual([])
  })
})

describe('inputChangesPrompt', () => {
  it('shows twelve lines and counts the rest', () => {
    const lines = Array.from({ length: 15 }, (_, i) => `• f${i}`)
    const prompt = inputChangesPrompt('Loading scenario "X"', lines)
    expect(prompt).toContain('changes 15 value(s)')
    expect(prompt).toContain('• f11')
    expect(prompt).not.toContain('• f12')
    expect(prompt).toContain('…and 3 more')
  })
})
