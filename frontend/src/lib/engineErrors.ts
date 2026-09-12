// Friendly rendering of engine 422s (B3c). The pro-forma engine refuses an
// untyped deal with `Missing or invalid required inputs: dealType`; that
// reads like a bug to the user, so compute/generate surfaces translate it
// into the action that fixes it.

export const UNTYPED_DEAL_MESSAGE =
  'This deal has no type yet — choose Acquisition or Development in the deal header, then try again.'

export function isMissingDealTypeError(message: string): boolean {
  return /\bdealType\b/.test(message)
}

export function friendlyEngineError(message: string): string {
  return isMissingDealTypeError(message) ? UNTYPED_DEAL_MESSAGE : message
}
