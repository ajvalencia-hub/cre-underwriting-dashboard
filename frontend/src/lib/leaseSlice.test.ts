import { describe, expect, it } from 'vitest'
import { annualize, sliceToCsv, type LeaseSlice } from './leaseSlice'

const slice: LeaseSlice = {
  suiteId: '100',
  tenant: 'Alpha',
  sf: 5000,
  recoveryType: 'NNN',
  endDate: '2028-06-30',
  scheduledRent: Array.from({ length: 18 }, () => 100),
  freeRent: [100, 100, ...Array.from({ length: 16 }, () => 0)],
  downtimeLoss: Array.from({ length: 18 }, () => 0),
  recoveries: Array.from({ length: 18 }, () => 25),
  leasingCapital: Array.from({ length: 18 }, () => 0),
  rolloverEvents: [],
}

describe('annualize', () => {
  it('buckets months into years, keeping the partial tail raw', () => {
    expect(annualize(slice.scheduledRent)).toEqual([1200, 600])
    expect(annualize(slice.freeRent)).toEqual([200, 0])
    expect(annualize([])).toEqual([])
  })
})

describe('sliceToCsv', () => {
  it('emits a header plus one row per series', () => {
    const csv = sliceToCsv(slice, 'annual')
    const lines = csv.split('\n')
    expect(lines[0]).toBe('Series,Year 1,Year 2')
    expect(lines).toHaveLength(6) // header + 5 series
    expect(lines[1]).toBe('"Scheduled rent",1200.00,600.00')
    expect(lines[4]).toContain('"Recoveries",300.00,150.00')
  })

  it('monthly mode keeps every month', () => {
    const csv = sliceToCsv(slice, 'monthly')
    expect(csv.split('\n')[0].split(',')).toHaveLength(19) // Series + 18 months
  })
})
