import { describe, expect, it } from 'vitest'
import { UNTYPED_DEAL_MESSAGE, friendlyEngineError, isMissingDealTypeError } from './engineErrors'

describe('friendlyEngineError', () => {
  it('translates the engine missing-dealType 422 into the header action', () => {
    const raw = 'Missing or invalid required inputs: dealType'
    expect(isMissingDealTypeError(raw)).toBe(true)
    expect(friendlyEngineError(raw)).toBe(UNTYPED_DEAL_MESSAGE)
  })

  it('leaves other messages untouched', () => {
    const raw = 'Missing or invalid required inputs: holdPeriodYears, exitCapRatePct'
    expect(friendlyEngineError(raw)).toBe(raw)
    expect(friendlyEngineError('500 Internal Server Error')).toBe('500 Internal Server Error')
  })
})
