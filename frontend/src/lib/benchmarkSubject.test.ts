import { describe, expect, it } from 'vitest'
import { deriveBenchmarkSubject } from './benchmarkSubject'

describe('deriveBenchmarkSubject', () => {
  it('computes unit-weighted average rent and bedroom mix from the unit mix table', () => {
    const subject = deriveBenchmarkSubject({
      unitMix: [
        { unitType: '1BR/1BA', unitCount: 60, inPlaceRent: 1400 },
        { unitType: '2BR/2BA', unitCount: 40, inPlaceRent: 1900 },
        { unitType: 'Studio', unitCount: 10, marketRent: 1100 },
      ],
    })
    // (60x1400 + 40x1900 + 10x1100) / 110
    expect(subject.avgRentMonthly).toBeCloseTo((84000 + 76000 + 11000) / 110, 6)
    expect(subject.bedroomMix).toEqual([
      { bedrooms: 1, count: 60 },
      { bedrooms: 2, count: 40 },
      { bedrooms: 0, count: 10 },
    ])
  })

  it('derives the expense ratio from expense lines against EGI', () => {
    const subject = deriveBenchmarkSubject({
      grossPotentialRent: 100_000,
      vacancyPct: 0.05,
      creditLossPct: 0,
      realEstateTaxes: 20_000,
      insurance: 8_000,
      managementFeePct: 0.03, // 3% of EGI 95,000 = 2,850
    })
    expect(subject.expenseRatioPct).toBeCloseTo((28_000 + 2_850) / 95_000, 6)
  })

  it('omits rent growth in flat mode and fields it cannot derive', () => {
    const flat = deriveBenchmarkSubject({ rentGrowthMode: 'flat', rentGrowthPct: 0.03 })
    expect(flat.rentGrowthPct).toBeUndefined()
    expect(flat.avgRentMonthly).toBeUndefined()
    expect(flat.expenseRatioPct).toBeUndefined()

    const growing = deriveBenchmarkSubject({ rentGrowthMode: 'per_year', rentGrowthPct: 0.03 })
    expect(growing.rentGrowthPct).toBe(0.03)
  })
})
