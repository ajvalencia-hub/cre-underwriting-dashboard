import { describe, expect, it } from 'vitest'
import {
  closingDateOf,
  dateStatus,
  daysUntil,
  hasDate,
  readCriticalDates,
  sortByDate,
  upcomingDeadlines,
} from './criticalDates'
import type { Deal } from '../types/deal'

const TODAY = new Date(2026, 6, 5) // 2026-07-05

function deal(id: string, name: string, dates: unknown): Deal {
  return {
    id,
    name,
    inputs: { criticalDates: dates },
    status: 'underwriting',
    activeTemplateId: null,
    activeMappingProfileId: null,
    createdAt: '',
    updatedAt: '',
  } as unknown as Deal
}

describe('daysUntil / dateStatus', () => {
  it('classifies overdue, upcoming (≤14d), and later', () => {
    expect(daysUntil('2026-07-04', TODAY)).toBe(-1)
    expect(dateStatus('2026-07-04', TODAY)).toBe('overdue')
    expect(dateStatus('2026-07-05', TODAY)).toBe('upcoming') // today counts
    expect(dateStatus('2026-07-19', TODAY)).toBe('upcoming') // day 14 inclusive
    expect(dateStatus('2026-07-20', TODAY)).toBe('later')
    expect(dateStatus('garbage', TODAY)).toBe('later') // unparsable never alarms
  })
})

describe('ordering', () => {
  it('sortByDate orders ascending; upcomingDeadlines puts most-overdue first', () => {
    const rows = [
      { id: 'a', label: 'Closing', date: '2026-08-01' },
      { id: 'b', label: 'LOI expiry', date: '2026-07-01' },
      { id: 'c', label: 'DD end', date: '2026-07-10' },
    ]
    expect(sortByDate(rows).map((r) => r.id)).toEqual(['b', 'c', 'a'])

    const entries = upcomingDeadlines(
      [deal('d1', 'Alpha', rows), deal('d2', 'Beta', [{ id: 'x', label: 'Closing', date: '2026-06-20' }])],
      TODAY,
    )
    // 2026-08-01 is beyond the 14-day window — excluded entirely.
    expect(entries.map((e) => e.row.id)).toEqual(['x', 'b', 'c'])
    expect(entries[0].status).toBe('overdue')
    expect(entries[0].days).toBe(-15)
    expect(entries[2].status).toBe('upcoming')
  })
})

describe('readCriticalDates', () => {
  it('tolerates junk shapes', () => {
    expect(readCriticalDates(undefined)).toEqual([])
    expect(readCriticalDates({ criticalDates: 'nope' })).toEqual([])
    expect(
      readCriticalDates({ criticalDates: [null, 42, { id: 'a', label: 'x', date: '2026-01-01' }] }),
    ).toHaveLength(1)
  })

  it('B11: skips rows with an empty or blank date', () => {
    const rows = readCriticalDates({
      criticalDates: [
        { id: 'a', label: 'Closing', date: '' },
        { id: 'b', label: 'LOI', date: '   ' },
        { id: 'c', label: 'DD end', date: '2026-07-10' },
      ],
    })
    expect(rows.map((r) => r.id)).toEqual(['c'])
    expect(hasDate({ date: '' })).toBe(false)
    expect(hasDate({ date: '2026-07-10' })).toBe(true)
  })
})

describe('closingDateOf', () => {
  const row = (label: string, date: string) => ({ id: label, label, date })
  it('prefers Closing, then Land closing, then any closing label', () => {
    expect(closingDateOf([row('LOI expiry', '2027-01-01'), row('Closing', '2027-03-15')])).toBe('2027-03-15')
    expect(closingDateOf([row('Groundbreaking', '2027-06-01'), row('Land closing', '2027-02-01')])).toBe('2027-02-01')
    expect(closingDateOf([row('Anticipated closing (lender)', '2027-04-30')])).toBe('2027-04-30')
    expect(closingDateOf([row('DD end', '2027-01-01'), row('Closing', 'soon')])).toBeNull()
  })
})
