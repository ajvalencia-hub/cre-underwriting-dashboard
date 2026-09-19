import { describe, expect, it } from 'vitest'
import { formatDelta } from './metricDelta'

describe('formatDelta', () => {
  it('uses the unit an analyst reads', () => {
    expect(formatDelta({ id: 'leveredIrr', type: 'percent' }, 0.0125)).toBe('+125 bps')
    expect(formatDelta({ id: 'equityMultiple', type: 'multiple' }, -0.153)).toBe('-0.15x')
    expect(formatDelta({ id: 'netSaleProceeds', type: 'currency' }, -120_000.4)).toBe('-$120,000')
    expect(formatDelta({ id: 'paybackPeriodYears', type: 'years' }, 0.5)).toBe('+0.5 yrs')
    expect(formatDelta({ id: 'x', type: 'percent' }, 0)).toBe('±0')
  })
})
