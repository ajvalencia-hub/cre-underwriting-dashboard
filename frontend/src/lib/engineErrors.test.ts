import { describe, expect, it } from 'vitest'
import { ApiError } from './api'
import { UNTYPED_DEAL_MESSAGE, friendlyEngineError, isMissingDealTypeError } from './engineErrors'

describe('friendlyEngineError', () => {
  it('translates the engine missing-dealType 422 into the header action', () => {
    const raw = 'Missing or invalid required inputs: dealType'
    expect(isMissingDealTypeError(raw)).toBe(true)
    expect(friendlyEngineError(raw)).toBe(UNTYPED_DEAL_MESSAGE)
    expect(friendlyEngineError(new Error(raw))).toBe(UNTYPED_DEAL_MESSAGE)
  })

  it("uses an ApiError's missing list without reading its text", () => {
    const err = new ApiError('Some inputs are missing', 422, ['dealType', 'holdPeriodYears'])
    expect(isMissingDealTypeError(err)).toBe(true)
    expect(friendlyEngineError(err)).toBe(UNTYPED_DEAL_MESSAGE)
  })

  it('leaves other messages untouched', () => {
    const raw = 'Missing or invalid required inputs: holdPeriodYears, exitCapRatePct'
    expect(friendlyEngineError(raw)).toBe(raw)
    expect(friendlyEngineError(new ApiError(raw, 422, ['holdPeriodYears']))).toBe(raw)
    expect(friendlyEngineError('500 Internal Server Error')).toBe('500 Internal Server Error')
  })

  it('falls back when nothing readable was thrown', () => {
    expect(friendlyEngineError(undefined)).toBe('Something went wrong')
    expect(friendlyEngineError(42, 'Run failed')).toBe('Run failed')
  })
})
