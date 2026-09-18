import { describe, expect, it } from 'vitest'
import type { OutputMetric } from '../types/schema'
import { formatOutputValue } from './formatValue'

describe('formatOutputValue', () => {
  it('shows the development spread in bps like the Quick Screen', () => {
    const metric = { id: 'developmentSpreadBps', label: 'Development Spread', type: 'percent' } as OutputMetric
    expect(formatOutputValue(metric, -0.0045)).toBe('-45 bps')
    expect(formatOutputValue({ ...metric, id: 'leveredIrr' }, 0.1423)).toBe('14.23%')
  })
})
