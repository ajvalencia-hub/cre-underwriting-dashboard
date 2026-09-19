import { describe, expect, it } from 'vitest'
import { headlineIds, isForSaleDeal } from './headlineMetrics'

describe('build-to-sell headline (roadmap #26)', () => {
  const homes = { dealType: 'development', propertyType: 'townhouse', isForSale: true, salePricePerHome: 450_000 }

  it('recognizes a for-sale deal only with a sale price, as the engine does', () => {
    expect(isForSaleDeal(homes)).toBe(true)
    expect(isForSaleDeal({ ...homes, salePricePerHome: undefined })).toBe(false)
    expect(isForSaleDeal({ ...homes, isForSale: false })).toBe(false)
    expect(isForSaleDeal({ ...homes, propertyType: 'multifamily' })).toBe(false)
  })

  it('leads with margin, peak equity and sellout', () => {
    expect(headlineIds('development', true)).toEqual([
      'leveredIrr', 'unleveredIrr', 'equityMultiple', 'grossMarginPct', 'peakEquity', 'selloutYears',
    ])
    expect(headlineIds('development')).toContain('yieldOnCost')
  })
})
