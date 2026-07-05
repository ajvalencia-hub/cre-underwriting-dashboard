import { describe, expect, it } from 'vitest'
import { daysSince, relativeAge, stalenessBadge } from './staleness'

const NOW = Date.parse('2026-07-04T12:00:00Z')
const daysAgo = (d: number) => new Date(NOW - d * 86_400_000).toISOString()

describe('daysSince', () => {
  it('floors partial days and never goes negative', () => {
    expect(daysSince(daysAgo(2.9), NOW)).toBe(2)
    expect(daysSince(daysAgo(-5), NOW)).toBe(0) // future timestamp
    expect(daysSince('garbage', NOW)).toBe(0)
  })
})

describe('stalenessBadge', () => {
  it('is silent under 14 days', () => {
    expect(stalenessBadge('underwriting', daysAgo(13), NOW)).toBeNull()
  })

  it('goes amber at 14 and red at 30', () => {
    expect(stalenessBadge('screening', daysAgo(14), NOW)).toEqual({
      label: 'stale 14d',
      tone: 'amber',
    })
    expect(stalenessBadge('loi', daysAgo(45), NOW)).toEqual({ label: 'stale 45d', tone: 'red' })
  })

  it('never flags terminal stages', () => {
    expect(stalenessBadge('closed', daysAgo(400), NOW)).toBeNull()
    expect(stalenessBadge('dead', daysAgo(400), NOW)).toBeNull()
  })
})

describe('relativeAge', () => {
  it('formats ages', () => {
    expect(relativeAge(daysAgo(0), NOW)).toBe('today')
    expect(relativeAge(daysAgo(1), NOW)).toBe('yesterday')
    expect(relativeAge(daysAgo(12), NOW)).toBe('12d ago')
    expect(relativeAge(daysAgo(90), NOW)).toBe('3mo ago')
    expect(relativeAge(daysAgo(800), NOW)).toBe('2y ago')
  })
})
