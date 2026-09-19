// Friendly rendering of engine 422s (Run 6 B3c). The pro-forma engine
// refuses an untyped deal with `Missing or invalid required inputs:
// dealType`; that reads like a bug to the user, so compute/generate
// surfaces translate it into the action that fixes it (the header's
// "Untyped — set type" chip).
//
// Panels call `friendlyEngineError(err)` at their `setError(...)` sites. It
// takes whatever was caught: an ApiError (its `missing[]` is checked first,
// no regex needed), any Error, or a plain message string.

import { ApiError } from './api'

export const UNTYPED_DEAL_MESSAGE =
  'This deal has no type yet — choose Acquisition or Development in the deal header, then try again.'

export function isMissingDealTypeError(error: unknown): boolean {
  if (error instanceof ApiError && error.missing.includes('dealType')) return true
  const message = typeof error === 'string' ? error : error instanceof Error ? error.message : ''
  return /\bdealType\b/.test(message)
}

/** The message to show for a failed engine call. `fallback` is used when
 *  the caught value carries no message at all. */
export function friendlyEngineError(error: unknown, fallback = 'Something went wrong'): string {
  if (isMissingDealTypeError(error)) return UNTYPED_DEAL_MESSAGE
  if (typeof error === 'string') return error || fallback
  if (error instanceof Error) return error.message || fallback
  return fallback
}
