import { describe, expect, it } from 'vitest'
import { MONTE_CARLO_POLL_TIMEOUT_MS, pollTimedOut, pollTimeoutMessage } from './monteCarloPolling'

describe('pollTimedOut', () => {
  it('is false inside the budget and true at/after the limit', () => {
    expect(pollTimedOut(0, MONTE_CARLO_POLL_TIMEOUT_MS - 1)).toBe(false)
    expect(pollTimedOut(0, MONTE_CARLO_POLL_TIMEOUT_MS)).toBe(true)
    expect(pollTimedOut(1000, 1000 + 5, 5)).toBe(true)
  })

  it('defaults to five minutes', () => {
    expect(MONTE_CARLO_POLL_TIMEOUT_MS).toBe(300_000)
    expect(pollTimeoutMessage()).toContain('5 minutes')
    expect(pollTimeoutMessage(60_000)).toContain('1 minute —')
  })
})
