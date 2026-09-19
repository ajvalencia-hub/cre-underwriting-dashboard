import { describe, expect, it } from 'vitest'
import { orderSections } from './sectionOrder'

describe('orderSections', () => {
  it('puts what the deal is and costs first, financing last, unknown sections at the end', () => {
    const ids = ['deal_basics', 'financing', 'equity_structure', 'operating_income', 'new_section', 'acquisition_specific']
    expect(orderSections(ids.map((id) => ({ id }))).map((s) => s.id)).toEqual([
      'deal_basics',
      'acquisition_specific',
      'operating_income',
      'financing',
      'equity_structure',
      'new_section',
    ])
  })
})
